"""eCommerce & price monitoring — easiest 2extract residential use case."""

from __future__ import annotations

import argparse

import _bootstrap

from twextract.client import ExtractClient
from twextract.config import DEFAULT_SCRAPE_COUNT, Settings
from twextract.ecommerce import run_price_monitor
from twextract.excel_export import write_ecommerce_excel
from twextract.geo_scrape import write_json
from twextract.username import Targeting, build_username


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape product name, price, and stock through a US residential proxy "
        "across DummyJSON store departments, then Open Prices shelf prices."
    )
    parser.add_argument("--country", default="us", help="ISO country for the residential exit IP (default us)")
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_SCRAPE_COUNT,
        help=f"How many products to scrape (default {DEFAULT_SCRAPE_COUNT})",
    )
    parser.add_argument("--pause", type=float, default=0.25, help="Seconds to wait between requests")
    parser.add_argument(
        "--listing-only",
        action="store_true",
        help="DummyJSON departments only (~194 products). Skip Open Products Facts fill.",
    )
    args = parser.parse_args()

    settings = Settings.load(require_proxy=True)
    creds = settings.residential_or_raise()
    targeting = Targeting(country=args.country, session="preview", time_minutes=30)
    print("Use case: eCommerce & Price Monitoring")
    print(f"Residential proxy: {creds.username} @ {creds.host}:{creds.port}")
    print(f"Shopper username example: {build_username(creds.username, targeting)}")
    if args.listing_only:
        print(f"Scraping up to {args.count} DummyJSON products across all store departments.")
    else:
        print(
            f"Scraping {args.count} mixed-category products with prices: DummyJSON departments "
            "(laptops, clothing, groceries, vehicles, ...) then Open Prices shelf prices."
        )
        if args.count >= DEFAULT_SCRAPE_COUNT:
            print("10000 priced rows usually takes about 20-45 minutes. Checkpoints every 100 rows.")
    print("Full rows go to Excel (not to this terminal).")

    with ExtractClient(creds) as client:
        rows, summary = run_price_monitor(
            client,
            country=args.country,
            count=args.count,
            pause_seconds=args.pause,
            dummyjson_only=args.listing_only,
        )

    json_path = write_json("ecommerce_results.json", {"summary": summary, "products": rows})
    excel_path = write_ecommerce_excel(rows, summary)
    ok_count = sum(1 for row in rows if row.get("ok"))
    categories = sorted({str(row.get("category")) for row in rows if row.get("category")})
    print(f"\nDone. {ok_count}/{len(rows)} products scraped across {len(categories)} categories.")
    print(f"Wrote {json_path}")
    print(f"Wrote {excel_path}")
    if ok_count == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    _bootstrap.guard(main)
