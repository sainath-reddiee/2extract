from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from twextract.client import ExtractClient
from twextract.config import ROOT
from twextract.errors import ExtractError, GatewayError
from twextract.ipcheck import inspect_exit_ip
from twextract.username import Targeting

OUTPUT_DIR = ROOT / "data" / "output"
STEAM_COOKIES = {"birthtime": "568022401", "wants_mature_content": "1"}
DEFAULT_APP_ID = "730"
QUOTES_URL = "https://quotes.toscrape.com/page/{page}/"
QUOTES_PAGES = 10


def load_locations() -> dict[str, Any]:
    return json.loads((ROOT / "locations.json").read_text(encoding="utf-8"))


def scrape_steam_price(
    client: ExtractClient,
    *,
    country: str,
    app_id: str = DEFAULT_APP_ID,
    targeting: Targeting | None = None,
) -> dict[str, Any]:
    """Regional Steam price. Same approach as the official Python Requests guide."""
    url = f"https://store.steampowered.com/app/{app_id}/"
    response = client.get(
        url,
        targeting=targeting or Targeting(country=country),
        params={"cc": country},
        cookies=STEAM_COOKIES,
        timeout=45,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    price = (
        soup.select_one("div.game_purchase_price")
        or soup.select_one("div.discount_final_price")
        or soup.select_one("[data-price-final]")
        or soup.select_one("div.game_purchase_action .price")
    )
    title = soup.select_one("#appHubAppName") or soup.select_one("div#appHubAppName")
    text = price.get_text(strip=True) if price else None
    if not text:
        meta = soup.select_one('meta[itemprop="price"]')
        if meta and meta.get("content"):
            text = str(meta["content"])
    return {
        "app_id": app_id,
        "title": title.get_text(strip=True) if title else None,
        "price": text,
        "http_status": response.status_code,
        "final_url": response.url,
    }


def scrape_quotes_page(client: ExtractClient, targeting: Targeting, page: int) -> list[dict[str, Any]]:
    """quotes.toscrape.com is a public practice site: 10 pages × 100 quotes = 1000 records."""
    response = client.get(QUOTES_URL.format(page=page), targeting=targeting, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    rows: list[dict[str, Any]] = []
    for quote in soup.select("div.quote"):
        text_el = quote.select_one("span.text")
        author_el = quote.select_one("small.author")
        rows.append(
            {
                "text": text_el.get_text(strip=True) if text_el else None,
                "author": author_el.get_text(strip=True) if author_el else None,
                "tags": [tag.get_text(strip=True) for tag in quote.select("a.tag")],
                "page": page,
                "source_url": response.url,
                "http_status": response.status_code,
            }
        )
    return rows


def run_geo_markets(
    client: ExtractClient,
    markets: list[dict[str, Any]] | None = None,
    *,
    app_id: str = DEFAULT_APP_ID,
    pause_seconds: float = 2.0,
    skip_steam: bool = False,
) -> list[dict[str, Any]]:
    markets = markets or load_locations()["geo_markets"]
    return run_geo_batch(
        client,
        countries=[str(m["country"]) for m in markets],
        count=len(markets),
        app_id=app_id,
        pause_seconds=pause_seconds,
        skip_steam=skip_steam,
        skip_quotes=True,
        labels={str(m["country"]): m.get("label") for m in markets},
        steam_every_row=not skip_steam,
    )


def run_geo_batch(
    client: ExtractClient,
    *,
    countries: list[str],
    count: int = 10000,
    app_id: str = DEFAULT_APP_ID,
    pause_seconds: float = 0.4,
    skip_steam: bool = True,
    skip_quotes: bool = False,
    labels: dict[str, str] | None = None,
    steam_every_row: bool = False,
    max_consecutive_failures: int = 5,
    max_attempts: int | None = None,
) -> list[dict[str, Any]]:
    """Collect `count` rotating residential hops. Each hop uses a new -session id."""
    if count < 1:
        raise ValueError("count must be at least 1")
    countries = [c.lower() for c in countries if c]
    if not countries:
        countries = ["us"]
    labels = labels or {}
    quote_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
    steam_cache: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    attempts = 0
    consecutive_failures = 0
    consecutive_duplicates = 0
    if max_attempts is None:
        max_attempts = max(count * 6, count)

    while len(rows) < count and attempts < max_attempts:
        attempts += 1
        index = len(rows)
        country = countries[(attempts - 1) % len(countries)]
        targeting = _rotating_geo_targeting(country)
        normalized = targeting.normalized()
        row: dict[str, Any] = {
            "row_number": index + 1,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "label": labels.get(country, country.upper()),
            "targeting": {
                "country": normalized.country,
                "state": None,
                "city": None,
                "zip": None,
                "session": normalized.session,
            },
            "ok": False,
        }
        try:
            row["exit"] = inspect_exit_ip(client, targeting)
            row["ok"] = True
        except GatewayError as exc:
            _raise_if_proxy_auth(exc)
            row["error"] = str(exc)
        except Exception as exc:
            _raise_if_proxy_auth(exc)
            row["error"] = str(exc)

        keys = geo_identity_keys(row)
        if not keys:
            consecutive_failures += 1
            consecutive_duplicates = 0
            reason = row.get("error") or "ipify returned no IP"
            print(f"skip empty geo IP: {reason}")
            _reset_client_connections(client)
            if consecutive_failures >= max_consecutive_failures:
                raise ExtractError(
                    f"Stopped after {consecutive_failures} failed IP checks in a row. "
                    "This is not a duplicate-IP skip. Last error: "
                    f"{reason}. If you see 407, open My Proxies and set Status to Active."
                )
            time.sleep(pause_seconds)
            continue
        if keys & seen_keys:
            consecutive_duplicates += 1
            ip = (row.get("exit") or {}).get("ip") or "no-ip"
            if consecutive_duplicates == 1 or consecutive_duplicates % 10 == 0:
                print(
                    f"skip duplicate geo IP ({ip}) x{consecutive_duplicates}; "
                    f"forcing a new session on {country.upper()}"
                )
            _reset_client_connections(client)
            time.sleep(min(4.0, pause_seconds + consecutive_duplicates * 0.15))
            continue

        consecutive_failures = 0
        consecutive_duplicates = 0

        if not skip_quotes:
            page = (index % QUOTES_PAGES) + 1
            slot = index % 10
            cache_key = (country, page)
            try:
                if cache_key not in quote_cache:
                    quote_cache[cache_key] = scrape_quotes_page(client, targeting, page)
                quotes = quote_cache[cache_key]
                if slot < len(quotes):
                    row["quote"] = quotes[slot]
            except Exception as exc:
                row["quote_error"] = str(exc)

        want_steam = (not skip_steam) and (steam_every_row or index == 0)
        if want_steam:
            try:
                if country not in steam_cache:
                    steam_cache[country] = scrape_steam_price(
                        client, country=country, app_id=app_id, targeting=targeting
                    )
                row["steam"] = steam_cache[country]
            except Exception as exc:
                row["steam_error"] = str(exc)

        seen_keys.update(keys)
        exit_info = row.get("exit") or {}
        quote = row.get("quote") or {}
        status = "ok" if row.get("ok") else "FAIL"
        print(
            f"[{len(rows) + 1}/{count}] {status} {country.upper()} "
            f"{exit_info.get('city') or '-'} {exit_info.get('region') or ''} "
            f"{exit_info.get('ip') or ''} | {(quote.get('author') or '')}".strip()
        )
        rows.append(row)
        _reset_client_connections(client)
        if len(rows) % 100 == 0:
            write_json("geo_results.json", rows)
            try:
                from twextract.excel_export import write_geo_excel

                write_geo_excel(rows)
                print(f"Checkpoint saved: {len(rows)} unique geo rows -> data/output/geo_address.xlsx")
            except OSError as exc:
                print(f"JSON saved ({len(rows)}). Close Excel if geo_address.xlsx is open: {exc}")
            except Exception as exc:
                print(f"JSON saved ({len(rows)}). Excel checkpoint skipped: {exc}")
        if len(rows) < count:
            time.sleep(pause_seconds)
    if len(rows) < count:
        print(f"Warning: collected {len(rows)} unique geo rows (requested {count}).")
    return rows


def _rotating_geo_targeting(country: str) -> Targeting:
    """A fresh -session id forces 2extract to assign a new exit IP for this hop."""
    return Targeting(country=country, session=uuid.uuid4().hex[:12], time_minutes=1)


def _reset_client_connections(client: Any) -> None:
    reset = getattr(client, "reset_connections", None)
    if callable(reset):
        reset()


def _raise_if_proxy_auth(exc: BaseException) -> None:
    if isinstance(exc, GatewayError) and exc.status_code in (401, 407):
        raise exc
    if "407" in str(exc):
        raise GatewayError(
            "2extract rejected the proxy login (407). Open My Proxies and set Status "
            f"to Active, then rerun. Detail: {exc}",
            status_code=407,
        )


def geo_identity_keys(row: dict[str, Any]) -> set[str]:
    ip = (row.get("exit") or {}).get("ip")
    if not ip:
        return set()
    return {f"ip:{str(ip).strip().lower()}"}


def write_json(name: str, payload: Any) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
