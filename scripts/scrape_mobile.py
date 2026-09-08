"""Mobile proxy scrape: carrier ISP targeting + mobile User-Agent."""

from __future__ import annotations

import argparse
import json
import uuid

import _bootstrap

from twextract.client import ExtractClient
from twextract.config import Settings
from twextract.excel_export import write_mobile_excel
from twextract.geo_scrape import load_locations, write_json
from twextract.mobile_scrape import run_mobile_isp
from twextract.username import Targeting, build_username


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape through a 2extract mobile proxy")
    parser.add_argument(
        "--isp",
        default="310260",
        help="Numeric mobile operator code. Default 310260 = T-Mobile US (docs example).",
    )
    parser.add_argument(
        "--sticky",
        action="store_true",
        help="Pin one mobile IP for this run with -session and -time-10",
    )
    args = parser.parse_args()

    settings = Settings.load(require_proxy=False)
    creds = settings.mobile_or_raise()
    session_id = uuid.uuid4().hex[:12] if args.sticky else None
    targeting = Targeting(isp=args.isp, session=session_id, time_minutes=10 if session_id else None)
    print("Username:", build_username(creds.username, targeting))
    print("ISP catalog: https://docs.2extract.com/data/isp.md")
    print("Do not combine -isp with -country/-city. That is a parameter conflict.")

    known = {row["isp"] for row in load_locations()["mobile_isps"]}
    if args.isp not in known:
        print(f"Note: {args.isp} is not in locations.json. Confirm it in the ISP catalog before spending traffic.")

    with ExtractClient(creds, timeout=45, max_retries=4) as client:
        result = run_mobile_isp(client, args.isp, session=session_id)

    json_path = write_json("mobile_results.json", result)
    excel_path = write_mobile_excel(result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nWrote {json_path}")
    print(f"Wrote {excel_path}")


if __name__ == "__main__":
    _bootstrap.guard(main)
