"""2extract Public API: geo lookup, balance, plans, proxy provisioning.

Auth header is X-API-Key (not Bearer). See https://docs.2extract.com/public-api/introduction.md
"""

from __future__ import annotations

from typing import Any

import requests

from twextract.config import API_BASE
from twextract.errors import ApiError


class ManagementAPI:
    def __init__(self, api_key: str, *, base_url: str = API_BASE, timeout: int = 30) -> None:
        if not api_key:
            raise ApiError("TWOEXTRACT_API_KEY is required for geo lookup and provisioning.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": api_key, "Accept": "application/json"})

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> ManagementAPI:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(
                f"Non-JSON response from {path} ({response.status_code}): {response.text[:300]}",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400 or payload.get("result") is False:
            raise ApiError(
                payload.get("error") or f"API error {response.status_code} on {path}",
                status_code=response.status_code,
                error_type=payload.get("error_type") or "",
            )
        return payload.get("data")

    def countries(self, search: str | None = None) -> list[dict[str, Any]]:
        params = {"search": search} if search else None
        return self._request("GET", "/v1/geo/countries", params=params)

    def states(self, country_code: str, search: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {"country_code": country_code.upper()}
        if search:
            params["search"] = search
        return self._request("GET", "/v1/geo/states", params=params)

    def cities(
        self,
        country_code: str,
        *,
        region: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"country_code": country_code.upper()}
        if region:
            params["region"] = region
        if search:
            params["search"] = search
        return self._request("GET", "/v1/geo/cities", params=params)

    def zips(self, country_code: str, city: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/v1/geo/zip",
            params={"country_code": country_code.upper(), "city": city},
        )

    def isp(self, search: str | None = None) -> list[dict[str, Any]]:
        """Carrier catalog for mobile -isp- codes. Falls back to a clear error if the route differs."""
        params = {"search": search} if search else None
        try:
            return self._request("GET", "/v1/geo/isp", params=params)
        except ApiError as exc:
            raise ApiError(
                "ISP lookup via API failed. Use the catalog at https://docs.2extract.com/data/isp.md "
                f"({exc})"
            ) from exc

    def balance(self) -> dict[str, Any]:
        return self._request("GET", "/v1/user/balance")

    def plans(self, proxy_type: str) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/plans", params={"proxy_type": proxy_type, "enabled": True})

    def list_proxies(self) -> Any:
        return self._request("GET", "/v1/proxy")

    def create_proxy(
        self,
        *,
        name: str,
        proxy_type: str,
        tariff_id: int,
        description: str = "",
    ) -> dict[str, Any]:
        body = {
            "name": name,
            "proxy_type": proxy_type,
            "tariff_id": tariff_id,
            "description": description,
        }
        return self._request("POST", "/v1/proxy", json=body)
