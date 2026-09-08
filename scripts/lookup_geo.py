"""Resolve place names to 2extract username parameters. Do not guess city/state slugs."""

from __future__ import annotations

import argparse
import json

import _bootstrap

from twextract.api import ManagementAPI
from twextract.config import Settings
from twextract.username import Targeting, build_username, slug


def main() -> None:
    parser = argparse.ArgumentParser(description="Look up 2extract geo targeting codes")
    parser.add_argument("--country", help="ISO country code or name search, e.g. US or India")
    parser.add_argument("--state", help="Region name search, e.g. California")
    parser.add_argument("--city", help="City name search, e.g. 'Los Angeles'")
    parser.add_argument("--zips", action="store_true", help="Also list ZIP codes for --city")
    parser.add_argument("--isp", help="Search mobile carrier catalog (if the geo ISP route is enabled)")
    args = parser.parse_args()

    settings = Settings.load(require_proxy=False, require_api=True)
    with ManagementAPI(settings.api_key) as api:
        if args.isp:
            print(json.dumps(api.isp(args.isp), indent=2, ensure_ascii=False))
            return

        if not args.country:
            parser.error("Pass --country (and optionally --state / --city) or --isp")

        countries = api.countries(args.country if len(args.country) > 2 else None)
        if len(args.country) == 2:
            code = args.country.upper()
            match = [c for c in countries if str(c.get("code", "")).upper() == code]
            countries = match or api.countries(args.country)
        print("Countries:")
        print(json.dumps(countries[:15], indent=2, ensure_ascii=False))
        if not countries:
            return

        country_code = (
            args.country.upper()
            if len(args.country) == 2
            else str(countries[0].get("code", "")).upper()
        )

        state_param = None
        if args.state:
            states = api.states(country_code, search=args.state)
            print("\nStates:")
            print(json.dumps(states[:20], indent=2, ensure_ascii=False))
            if states:
                state_param = states[0].get("extract_parameter") or slug(args.state)

        city_param = None
        if args.city:
            cities = api.cities(country_code, region=args.state, search=args.city)
            print("\nCities:")
            print(json.dumps(cities[:20], indent=2, ensure_ascii=False))
            if cities:
                city_param = cities[0].get("extract_parameter") or slug(args.city)
            if args.zips:
                zips = api.zips(country_code, args.city)
                print("\nZIP codes:")
                print(json.dumps(zips[:30], indent=2, ensure_ascii=False))

        targeting = Targeting(country=country_code.lower(), state=state_param, city=city_param)
        suffix = build_username("BASE", targeting)
        if suffix.startswith("BASE-"):
            suffix = suffix[5:]
        print("\nUsername suffix to append:")
        print(f"  -{suffix}")
        print("Docs: https://docs.2extract.com/public-api/geo.md")


if __name__ == "__main__":
    _bootstrap.guard(main)
