"""Market Research scrape through a 2extract residential proxy.

Writes market_research.xlsx only. This is not geo_address or eCommerce.
"""

from __future__ import annotations

import argparse

import _bootstrap

from twextract.client import ExtractClient
from twextract.config import DEFAULT_SCRAPE_COUNT, Settings
from twextract.excel_export import write_market_research_excel
from twextract.geo_scrape import write_json
from twextract.market_research import run_market_research
from twextract.username import Targeting, build_username


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect public market-research rows (trends, sentiment, intelligence) "
        "through a US residential proxy."
    )
    parser.add_argument("--country", default="us", help="ISO country for the residential exit IP (default us)")
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_SCRAPE_COUNT,
        help=f"How many unique research rows to scrape (default {DEFAULT_SCRAPE_COUNT})",
    )
    parser.add_argument("--pause", type=float, default=0.2, help="Seconds to wait between requests")
    args = parser.parse_args()

    settings = Settings.load(require_proxy=True)
    creds = settings.residential_or_raise()
    targeting = Targeting(country=args.country, session="preview", time_minutes=30)
    print("Use case: Market Research")
    print(f"Residential proxy: {creds.username} @ {creds.host}:{creds.port}")
    print(f"Analyst username example: {build_username(creds.username, targeting)}")
    print(
        f"Scraping {args.count} public rows: Hacker News trends/sentiment and "
        "Open Food Facts brand intelligence (not DummyJSON)."
    )
    print("Writes data/output/market_research.xlsx only — not geo_address.xlsx or eCommerce.xlsx.")
    if args.count >= DEFAULT_SCRAPE_COUNT:
        print("10000 research rows usually takes about 15-40 minutes. Checkpoints every 100 rows.")
    print("Full rows go to Excel (not to this terminal).")

    with ExtractClient(creds) as client:
        rows, summary = run_market_research(
            client,
            country=args.country,
            count=args.count,
            pause_seconds=args.pause,
        )

    json_path = write_json("market_research_results.json", {"summary": summary, "rows": rows})
    excel_path = write_market_research_excel(rows, summary)
    ok_count = sum(1 for row in rows if row.get("ok"))
    types = sorted({str(row.get("record_type")) for row in rows if row.get("record_type")})
    print(f"\nDone. {ok_count}/{len(rows)} research rows across {len(types)} types.")
    print(f"Wrote {json_path}")
    print(f"Wrote {excel_path}")
    if ok_count == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    _bootstrap.guard(main)
