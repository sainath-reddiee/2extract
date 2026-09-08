from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from twextract.client import MOBILE_UA, ExtractClient
from twextract.ipcheck import inspect_exit_ip
from twextract.username import Targeting

IP_API = "http://ip-api.com/json/"
WIKI_MOBILE = "https://en.m.wikipedia.org/wiki/Mobile_broadband"


def carrier_lookup(client: ExtractClient, targeting: Targeting) -> dict[str, Any]:
    """ip-api includes a `mobile` flag, which ipapi.co does not."""
    response = client.get(
        IP_API,
        targeting=targeting,
        params={"fields": "status,message,country,countryCode,regionName,city,zip,isp,org,as,mobile,proxy,query"},
        headers={"User-Agent": MOBILE_UA},
    )
    response.raise_for_status()
    return response.json()


def scrape_mobile_page(client: ExtractClient, targeting: Targeting, url: str = WIKI_MOBILE) -> dict[str, Any]:
    response = client.get(url, targeting=targeting, headers={"User-Agent": MOBILE_UA})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    title = soup.select_one("h1") or soup.select_one("title")
    paragraph = soup.select_one("div.mw-parser-output > p")
    return {
        "url": response.url,
        "http_status": response.status_code,
        "title": title.get_text(strip=True) if title else None,
        "lead": paragraph.get_text(strip=True)[:500] if paragraph else None,
    }


def run_mobile_isp(client: ExtractClient, isp: str, *, session: str | None = None) -> dict[str, Any]:
    targeting = Targeting(isp=isp, session=session, time_minutes=10 if session else None)
    result: dict[str, Any] = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "isp_code": isp,
        "session": session,
    }
    result["exit"] = inspect_exit_ip(client, targeting)
    result["carrier"] = carrier_lookup(client, targeting)
    result["page"] = scrape_mobile_page(client, targeting)
    result["ok"] = True
    return result
