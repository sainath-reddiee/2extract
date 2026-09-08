from __future__ import annotations

import logging
import random
import time
import warnings
from typing import Any
from urllib.parse import quote

import requests
from requests.exceptions import ProxyError, SSLError
from urllib3.exceptions import InsecureRequestWarning

from twextract.config import ProxyCredentials
from twextract.errors import GatewayError
from twextract.username import Targeting, build_username

LOGGER = logging.getLogger("twextract")

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
)

RETRYABLE_STATUS = {429, 502, 504}
AUTH_STATUS = {401, 407}
_HEADER_UNSET = object()


class ExtractClient:
    """HTTP client that routes every request through the 2extract gateway."""

    def __init__(self, credentials: ProxyCredentials, *, timeout: int = 45, max_retries: int = 3) -> None:
        self.credentials = credentials
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self._protocol = credentials.protocol
        self._cached_407_header: str | None | object = _HEADER_UNSET
        # urllib3 warns when the hop to an HTTPS proxy is not verified like a website.
        warnings.filterwarnings("ignore", category=InsecureRequestWarning)

    def close(self) -> None:
        self.session.close()

    def reset_connections(self) -> None:
        """Drop keep-alive sockets so the next request can pick a new residential IP."""
        self.session.close()
        self.session = requests.Session()

    def __enter__(self) -> ExtractClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def proxies_for(self, targeting: Targeting | None = None) -> dict[str, str]:
        # Hyphens in the username are the targeting separator — do not percent-encode them.
        username = build_username(self.credentials.username, targeting)
        password = quote(self.credentials.password, safe="")
        proxy_url = (
            f"{self._protocol}://{username}:{password}"
            f"@{self.credentials.host}:{self.credentials.port}"
        )
        return {"http": proxy_url, "https": proxy_url}

    def request(
        self,
        method: str,
        url: str,
        *,
        targeting: Targeting | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        merged_headers = {"User-Agent": DESKTOP_UA, "Accept-Language": "en-US,en;q=0.9"}
        if headers:
            merged_headers.update(headers)
        kwargs.setdefault("timeout", self.timeout)
        kwargs["headers"] = merged_headers

        last_error: Exception | None = None
        protocols = [self._protocol]
        if self._protocol == "https" and "http" not in protocols:
            protocols.append("http")

        for protocol in protocols:
            self._protocol = protocol
            kwargs["proxies"] = self.proxies_for(targeting)
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = self.session.request(method, url, **kwargs)
                except (SSLError, ProxyError) as exc:
                    last_error = exc
                    if _is_407(exc):
                        raise self._gateway_407(targeting, exc)
                    if protocol == "https" and _looks_like_proxy_tls_failure(exc):
                        LOGGER.warning("HTTPS proxy failed (%s); retrying the gateway over HTTP", exc)
                        break
                    LOGGER.warning("Attempt %s/%s failed: %s", attempt, self.max_retries, exc)
                    if attempt < self.max_retries:
                        _backoff(attempt)
                        continue
                    break
                except requests.RequestException as exc:
                    last_error = exc
                    LOGGER.warning("Attempt %s/%s failed: %s", attempt, self.max_retries, exc)
                    if attempt < self.max_retries:
                        _backoff(attempt)
                        continue
                    break

                gateway = (
                    response.headers.get("X-2extract-Error")
                    or response.headers.get("X-Proxy-Error")
                    or ""
                )
                if response.status_code in AUTH_STATUS:
                    raise GatewayError(
                        f"2extract rejected the proxy login ({response.status_code}): "
                        f"{gateway or 'check TWOEXTRACT_USERNAME / TWOEXTRACT_PASSWORD'}",
                        status_code=response.status_code,
                        gateway_header=gateway or None,
                    )
                if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                    LOGGER.warning(
                        "Gateway/status %s (%s). Retry %s/%s",
                        response.status_code,
                        gateway or "no header",
                        attempt,
                        self.max_retries,
                    )
                    _backoff(attempt)
                    continue
                if gateway and response.status_code >= 400:
                    raise GatewayError(
                        f"2extract gateway error {response.status_code}: {gateway}",
                        status_code=response.status_code,
                        gateway_header=gateway,
                    )
                if protocol == "http" and self.credentials.protocol == "https":
                    LOGGER.info("Using HTTP to the gateway (this client could not speak HTTPS to the proxy)")
                return response

        raise GatewayError(f"Request failed after {self.max_retries} attempts: {last_error}")

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def _gateway_407(self, targeting: Targeting | None, exc: Exception) -> GatewayError:
        if self._cached_407_header is _HEADER_UNSET:
            self._cached_407_header = _read_gateway_header(self.proxies_for(targeting))
        header = self._cached_407_header
        hint = header or (
            "the proxy is Inactive, the password is wrong, or the wallet is empty. "
            "Open My Proxies and set Status to Active, then rerun."
        )
        if header and "inactive" in header.lower():
            hint = (
                f"{header}. Open My Proxies, find this proxy, and set Status to Active "
                "(Actions menu). Inactive proxies always return 407."
            )
        return GatewayError(
            f"2extract rejected the proxy login (407): {hint}",
            status_code=407,
            gateway_header=header,
        )


def _is_407(exc: BaseException) -> bool:
    return "407" in str(exc)


def _read_gateway_header(proxies: dict[str, str]) -> str | None:
    """HTTPS CONNECT hides gateway headers. A plain HTTP fetch returns X-Proxy-Error."""
    from requests.adapters import HTTPAdapter

    http_proxies = {key: value.replace("https://", "http://", 1) for key, value in proxies.items()}
    try:
        with requests.Session() as session:
            session.mount("http://", HTTPAdapter(max_retries=0))
            session.mount("https://", HTTPAdapter(max_retries=0))
            response = session.get(
                "http://api.ipify.org/?format=json",
                proxies=http_proxies,
                timeout=8,
            )
        return response.headers.get("X-Proxy-Error") or response.headers.get("X-2extract-Error")
    except Exception:
        return None


def _looks_like_proxy_tls_failure(exc: BaseException) -> bool:
    text = str(exc).upper()
    markers = ("SSL", "TLS", "CERTIFICATE", "WRONG_VERSION_NUMBER", "UNEXPECTED_EOF")
    return any(marker in text for marker in markers)


def _backoff(attempt: int) -> None:
    time.sleep(min(8.0, (2 ** attempt) * 0.4) + random.uniform(0, 0.4))
