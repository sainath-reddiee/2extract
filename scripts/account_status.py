"""Show account balance and existing proxies. Requires TWOEXTRACT_API_KEY."""

from __future__ import annotations

import json

import _bootstrap

from twextract.api import ManagementAPI
from twextract.config import Settings


def _summarize_proxy(item: dict) -> dict:
    keys = ("id", "name", "status", "type", "host", "port")
    return {k: item.get(k) for k in keys if k in item}


def main() -> None:
    settings = Settings.load(require_proxy=False, require_api=True)
    with ManagementAPI(settings.api_key) as api:
        balance = api.balance()
        proxies = api.list_proxies()

    print("Balance:")
    print(json.dumps(balance, indent=2))
    print("\nProxies:")
    if isinstance(proxies, list):
        print(json.dumps([_summarize_proxy(p) if isinstance(p, dict) else p for p in proxies], indent=2))
    elif isinstance(proxies, dict) and "items" in proxies:
        print(json.dumps([_summarize_proxy(p) for p in proxies["items"]], indent=2))
    else:
        print(json.dumps(proxies, indent=2))


if __name__ == "__main__":
    _bootstrap.guard(main)
