"""Build 2extract gateway usernames.

All proxy behaviour is controlled through the username, not headers.

Format:
    2xt-customer-[CLIENT_ID]-proxy-[PROXY_NAME]-[param]-[value]-...

Rules from https://docs.2extract.com/proxy-products/configuration/geo-targeting.md
and https://docs.2extract.com/proxy-products/configuration/session.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from twextract.errors import TargetingError

_SESSION_RE = re.compile(r"^[A-Za-z0-9]+$")
_COUNTRY_RE = re.compile(r"^[a-z]{2}$")
_SLUG_RE = re.compile(r"^[a-z0-9]+$")
_ZIP_RE = re.compile(r"^[a-z0-9]+$")
_NUM_RE = re.compile(r"^[0-9]+$")


def slug(value: str) -> str:
    """Turn a place name into a 2extract parameter: 'Los Angeles' -> 'losangeles'."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).lower()
    if not cleaned:
        raise TargetingError(f"Cannot build a targeting slug from {value!r}.")
    return cleaned


@dataclass(frozen=True)
class Targeting:
    country: str | None = None
    state: str | None = None
    city: str | None = None
    zip_code: str | None = None
    asn: str | None = None
    isp: str | None = None
    session: str | None = None
    time_minutes: int | None = None
    const: bool = False

    def normalized(self) -> Targeting:
        country = self.country.lower() if self.country else None
        state = slug(self.state) if self.state else None
        city = slug(self.city) if self.city else None
        zip_code = self.zip_code.replace(" ", "").lower() if self.zip_code else None
        asn = str(self.asn).strip() if self.asn else None
        isp = str(self.isp).strip() if self.isp else None
        session = self.session.strip() if self.session else None
        return Targeting(
            country=country,
            state=state,
            city=city,
            zip_code=zip_code,
            asn=asn,
            isp=isp,
            session=session,
            time_minutes=self.time_minutes,
            const=self.const,
        )

    def validate(self) -> None:
        t = self.normalized()
        geo = any([t.country, t.state, t.city, t.zip_code])
        net = any([t.asn, t.isp])
        if geo and net:
            raise TargetingError(
                "Geographic targeting (country/state/city/zip) and network targeting "
                "(asn/isp) are mutually exclusive. Use one group only."
            )
        if (t.state or t.city or t.zip_code) and not t.country:
            raise TargetingError("city, state and zip require country in the same username.")
        if t.country and not _COUNTRY_RE.fullmatch(t.country):
            raise TargetingError("country must be a 2-letter ISO code such as us, de, in. Not 'usa'.")
        if t.state and not _SLUG_RE.fullmatch(t.state):
            raise TargetingError("state must be lowercase letters/digits with no hyphens (california, newyork).")
        if t.city and not _SLUG_RE.fullmatch(t.city):
            raise TargetingError("city must be lowercase letters/digits with no hyphens (losangeles, berlin).")
        if t.zip_code and not _ZIP_RE.fullmatch(t.zip_code):
            raise TargetingError("zip must be alphanumeric with no spaces or hyphens.")
        if t.asn and not _NUM_RE.fullmatch(t.asn):
            raise TargetingError("asn must be a number, e.g. 7922.")
        if t.isp and not _NUM_RE.fullmatch(t.isp):
            raise TargetingError("isp must be the numeric operator code, e.g. 310260 for T-Mobile US.")
        if t.time_minutes is not None and t.session is None:
            raise TargetingError("-time requires -session.")
        if t.const and t.session is None:
            raise TargetingError("-const requires -session.")
        if t.time_minutes is not None and (t.time_minutes < 1 or t.time_minutes != int(t.time_minutes)):
            raise TargetingError("time must be a whole number of minutes.")
        if t.session and not _SESSION_RE.fullmatch(t.session):
            raise TargetingError("session id must be alphanumeric. Hyphens are the parameter separator.")

    def suffix_parts(self) -> list[str]:
        t = self.normalized()
        t.validate()
        parts: list[str] = []
        if t.country:
            parts += ["country", t.country]
        if t.state:
            parts += ["state", t.state]
        if t.city:
            parts += ["city", t.city]
        if t.zip_code:
            parts += ["zip", t.zip_code]
        if t.asn:
            parts += ["asn", t.asn]
        if t.isp:
            parts += ["isp", t.isp]
        if t.session:
            parts += ["session", t.session]
        if t.time_minutes is not None:
            parts += ["time", str(int(t.time_minutes))]
        if t.const:
            parts.append("const")
        return parts


def build_username(base_username: str, targeting: Targeting | None = None) -> str:
    base = base_username.strip()
    if not base:
        raise TargetingError("Base proxy username is empty.")
    if targeting is None:
        return base
    parts = targeting.suffix_parts()
    if not parts:
        return base
    return f"{base}-{'-'.join(parts)}"
