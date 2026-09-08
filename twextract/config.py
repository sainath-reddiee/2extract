from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from twextract.errors import ExtractError

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

DEFAULT_HOST = "proxy.2extract.net"
DEFAULT_PORT = 5555
API_BASE = "https://api.2extract.com"
DEFAULT_SCRAPE_COUNT = 10000


def _optional(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _require(name: str) -> str:
    value = _optional(name)
    if not value:
        raise ExtractError(
            f"Missing {name}. Copy .env.example to .env and paste values from the 2extract dashboard."
        )
    return value


@dataclass(frozen=True)
class ProxyCredentials:
    username: str
    password: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    protocol: str = "https"

    def __post_init__(self) -> None:
        protocol = self.protocol.lower()
        if protocol not in {"http", "https"}:
            raise ExtractError("TWOEXTRACT_PROTOCOL must be http or https.")
        object.__setattr__(self, "protocol", protocol)
        if not self.username:
            raise ExtractError("Proxy username is empty.")
        if re_has_targeting(self.username):
            raise ExtractError(
                "TWOEXTRACT_USERNAME must be the base username only "
                "(2xt-customer-...-proxy-name). Targeting params are added in code."
            )


def re_has_targeting(username: str) -> bool:
    return bool(re.search(r"-(country|state|city|zip|asn|isp|session)-", username))


@dataclass(frozen=True)
class Settings:
    residential: ProxyCredentials | None
    mobile: ProxyCredentials | None
    api_key: str
    api_base: str = API_BASE

    @classmethod
    def load(cls, *, require_proxy: bool = True, require_api: bool = False) -> Settings:
        host = _optional("TWOEXTRACT_HOST") or DEFAULT_HOST
        port = int(_optional("TWOEXTRACT_PORT") or DEFAULT_PORT)
        protocol = _optional("TWOEXTRACT_PROTOCOL") or "https"

        residential = None
        username = _require("TWOEXTRACT_USERNAME") if require_proxy else _optional("TWOEXTRACT_USERNAME")
        password = _require("TWOEXTRACT_PASSWORD") if require_proxy else _optional("TWOEXTRACT_PASSWORD")
        if username:
            residential = ProxyCredentials(
                username=username,
                password=password,
                host=host,
                port=port,
                protocol=protocol,
            )

        mobile = None
        mobile_user = _optional("TWOEXTRACT_MOBILE_USERNAME")
        if mobile_user:
            mobile_pass = _optional("TWOEXTRACT_MOBILE_PASSWORD") or (residential.password if residential else "")
            if not mobile_pass:
                raise ExtractError(
                    "TWOEXTRACT_MOBILE_PASSWORD is required when TWOEXTRACT_MOBILE_USERNAME is set."
                )
            mobile = ProxyCredentials(
                username=mobile_user,
                password=mobile_pass,
                host=host,
                port=port,
                protocol=protocol,
            )

        api_key = _require("TWOEXTRACT_API_KEY") if require_api else _optional("TWOEXTRACT_API_KEY")
        return cls(residential=residential, mobile=mobile, api_key=api_key)

    def residential_or_raise(self) -> ProxyCredentials:
        if self.residential is None:
            raise ExtractError("Set TWOEXTRACT_USERNAME and TWOEXTRACT_PASSWORD in .env")
        return self.residential

    def mobile_or_raise(self) -> ProxyCredentials:
        if self.mobile is None:
            raise ExtractError(
                "Mobile ISP targeting needs a mobile proxy. Create one named like mobile_scraper "
                "in the dashboard (proxy type: Mobile) and set TWOEXTRACT_MOBILE_USERNAME / PASSWORD."
            )
        return self.mobile
