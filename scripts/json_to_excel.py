"""Turn a scrape JSON file into an Excel table (one column per JSON key)."""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap

from twextract.excel_export import OUTPUT_DIR, ingest_json_file, ingest_output_folder


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert scrape JSON into Excel columns matching every key")
    parser.add_argument("json_file", nargs="?", help="JSON file to convert. Default: all files in data/output")
    parser.add_argument("--sheet", help="Excel sheet name")
    args = parser.parse_args()

    if args.json_file:
        path = Path(args.json_file)
        if not path.is_file():
            path = OUTPUT_DIR / args.json_file
        excel_path = ingest_json_file(path, args.sheet)
        print(f"Wrote {excel_path} from {path} ({path.stat().st_size} bytes JSON)")
        return

    paths = ingest_output_folder()
    if not paths:
        print(f"No JSON files found in {OUTPUT_DIR}")
        return
    for excel_path in paths:
        print(f"Wrote {excel_path}")


if __name__ == "__main__":
    _bootstrap.guard(main)
