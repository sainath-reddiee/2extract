from __future__ import annotations

from typing import Any

import requests

from twextract.client import ExtractClient
from twextract.username import Targeting

IPIFY = "https://api.ipify.org?format=json"
IP_API = "http://ip-api.com/json/{ip}"
IPAPI = "https://ipapi.co/{ip}/json/"


def inspect_exit_ip(client: ExtractClient, targeting: Targeting | None = None) -> dict[str, Any]:
    """Confirm the proxy exit IP, then geolocate that same IP (not a second rotating hop)."""
    ip_response = client.get(IPIFY, targeting=targeting)
    ip_response.raise_for_status()
    payload = ip_response.json()
    ip = payload["ip"] if isinstance(payload, dict) else str(payload)
    location = _geolocate_ip(ip)
    return {
        "ip": ip,
        "country": location.get("country_name") or location.get("country"),
        "country_code": location.get("country_code") or location.get("countryCode"),
        "region": location.get("region") or location.get("regionName"),
        "city": location.get("city"),
        "postal": location.get("postal") or location.get("zip"),
        "org": location.get("org") or location.get("isp"),
        "asn": location.get("asn") or location.get("as"),
        "network": location.get("network"),
        "raw": location,
    }


def _geolocate_ip(ip: str) -> dict[str, Any]:
    """Look up the exit IP directly so location matches the address we just collected."""
    try:
        response = requests.get(
            IP_API.format(ip=ip),
            params={"fields": "status,country,countryCode,regionName,city,zip,isp,org,as,query"},
            timeout=10,
        )
        if response.ok:
            data = response.json()
            if isinstance(data, dict) and data.get("status") == "success":
                return data
    except requests.RequestException:
        pass
    try:
        response = requests.get(IPAPI.format(ip=ip), timeout=10)
        if response.ok:
            data = response.json()
            if isinstance(data, dict) and not data.get("error"):
                return data
    except requests.RequestException:
        pass
    return {}
