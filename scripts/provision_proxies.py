"""Create one residential and one mobile PAYG proxy via the Public API.

Proxy names: lowercase letters, digits, underscores. Hyphens are forbidden.
One residential proxy covers every country — do not create one proxy per market.
"""

from __future__ import annotations

import argparse
import json
import re

import _bootstrap

from twextract.api import ManagementAPI
from twextract.config import Settings
from twextract.errors import ExtractError

NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _pick_tariff(plans: list[dict]) -> dict:
    if not plans:
        raise ExtractError("No enabled plans returned. Top up your balance, then retry GET /v1/plans.")
    return plans[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision geo (residential) and mobile 2extract proxies")
    parser.add_argument("--residential-name", default="geo_scraper")
    parser.add_argument("--mobile-name", default="mobile_scraper")
    parser.add_argument("--skip-mobile", action="store_true")
    parser.add_argument("--skip-residential", action="store_true")
    args = parser.parse_args()

    for name in (args.residential_name, args.mobile_name):
        if not NAME_RE.fullmatch(name):
            raise SystemExit(
                f"Invalid proxy name {name!r}. Use lowercase letters, digits and underscores only. No hyphens."
            )

    settings = Settings.load(require_proxy=False, require_api=True)
    created = []
    with ManagementAPI(settings.api_key) as api:
        if not args.skip_residential:
            plan = _pick_tariff(api.plans("residential"))
            print(f"Residential plan: id={plan.get('id')} title={plan.get('title')}")
            created.append(
                api.create_proxy(
                    name=args.residential_name,
                    proxy_type="residential",
                    tariff_id=int(plan["id"]),
                    description="Geo-targeted scraping (country/state/city/zip)",
                )
            )
        if not args.skip_mobile:
            plan = _pick_tariff(api.plans("mobile"))
            print(f"Mobile plan: id={plan.get('id')} title={plan.get('title')}")
            created.append(
                api.create_proxy(
                    name=args.mobile_name,
                    proxy_type="mobile",
                    tariff_id=int(plan["id"]),
                    description="Mobile carrier scraping (-isp-)",
                )
            )

    print(json.dumps(created, indent=2))
    print("\nCopy username + password into .env:")
    print("  TWOEXTRACT_USERNAME / TWOEXTRACT_PASSWORD          <- residential")
    print("  TWOEXTRACT_MOBILE_USERNAME / TWOEXTRACT_MOBILE_PASSWORD  <- mobile")
    print("The password is shown only at creation. Do not commit it.")


if __name__ == "__main__":
    _bootstrap.guard(main)
