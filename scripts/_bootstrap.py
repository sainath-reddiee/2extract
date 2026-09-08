"""Shared path bootstrap so scripts work as `python scripts/foo.py` on Windows."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def guard(fn) -> None:
    from twextract.errors import ApiError, ExtractError, GatewayError

    try:
        fn()
    except (ExtractError, ApiError, GatewayError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
