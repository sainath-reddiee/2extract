"""Step 1 after .env: prove the residential gateway accepts your credentials."""

from __future__ import annotations

import argparse
import json

import _bootstrap

from twextract.client import ExtractClient
from twextract.config import Settings
from twextract.excel_export import write_connectivity_excel
from twextract.ipcheck import inspect_exit_ip
from twextract.username import Targeting, build_username


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify 2extract residential proxy credentials")
    parser.add_argument(
        "--country",
        default="us",
        help="Also request a geo-targeted IP (default us). Pass empty string to skip.",
    )
    args = parser.parse_args()

    settings = Settings.load(require_proxy=True)
    creds = settings.residential_or_raise()
    print(f"Host: {creds.host}:{creds.port}")
    print(f"Base username: {creds.username}")
    print(f"Protocol: {creds.protocol}")

    with ExtractClient(creds) as client:
        rotating = inspect_exit_ip(client)
        result = {"rotating": rotating, "gateway_protocol": client._protocol}

        if args.country:
            targeting = Targeting(country=args.country)
            print(f"Geo username: {build_username(creds.username, targeting)}")
            result["geo"] = {
                "targeting": args.country,
                "exit": inspect_exit_ip(client, targeting),
            }

    excel_path = write_connectivity_excel(result)
    print("Gateway OK. Exit IP through 2extract:")
    print(json.dumps(result, indent=2))
    print(f"\nWrote {excel_path}")


if __name__ == "__main__":
    _bootstrap.guard(main)
