"""Geo / address scrape through a 2extract residential proxy.

Writes geo_address.xlsx only. This is not the eCommerce catalog.
"""

from __future__ import annotations

import argparse

import _bootstrap

from twextract.client import ExtractClient
from twextract.config import DEFAULT_SCRAPE_COUNT, Settings
from twextract.excel_export import write_geo_excel
from twextract.geo_scrape import load_locations, run_geo_batch, write_json
from twextract.username import Targeting, build_username


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate residential IPs by country and write unique geo_address rows "
        "(separate from eCommerce.xlsx)."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_SCRAPE_COUNT,
        help=f"How many unique geo rows to collect (default {DEFAULT_SCRAPE_COUNT})",
    )
    parser.add_argument("--pause", type=float, default=0.4, help="Seconds to wait between requests")
    parser.add_argument("--skip-quotes", action="store_true", help="Do not attach quotes.toscrape.com text")
    args = parser.parse_args()

    settings = Settings.load(require_proxy=True)
    creds = settings.residential_or_raise()
    markets = load_locations()["geo_markets"]
    countries = [str(m["country"]) for m in markets]
    labels = {str(m["country"]): m.get("label") for m in markets}
    targeting = Targeting(country=countries[0] if countries else "us", session="hop1", time_minutes=1)
    print("Use case: Geo / address")
    print(f"Residential proxy: {creds.username} @ {creds.host}:{creds.port}")
    print(f"Username example: {build_username(creds.username, targeting)} (new session each hop)")
    print(f"Collecting {args.count} unique geo rows (duplicate IPs are skipped).")
    print("Writes data/output/geo_address.xlsx only — not eCommerce.xlsx.")
    if args.count >= DEFAULT_SCRAPE_COUNT:
        print("10000 unique residential IPs usually takes several hours. Checkpoints every 100 rows.")
    elif args.count >= 1000:
        print("1000 unique residential IPs usually takes about 15-40 minutes.")

    with ExtractClient(creds) as client:
        rows = run_geo_batch(
            client,
            countries=countries or ["us"],
            count=args.count,
            pause_seconds=args.pause,
            skip_steam=True,
            skip_quotes=args.skip_quotes,
            labels=labels,
        )

    json_path = write_json("geo_results.json", rows)
    excel_path = write_geo_excel(rows)
    ok_count = sum(1 for row in rows if row.get("ok"))
    print(f"\nDone. {ok_count}/{len(rows)} unique geo rows.")
    print(f"Wrote {json_path}")
    print(f"Wrote {excel_path}")
    if ok_count == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    _bootstrap.guard(main)
