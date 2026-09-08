"""eCommerce & price monitoring through a 2extract residential proxy.

Use case from https://docs.2extract.com/proxy-products/residential/introduction-use-cases.md

Walks every DummyJSON store department (beauty, laptops, furniture, groceries,
clothing, vehicles, ...) which includes price and stock, then fills remaining
rows from Open Prices (crowd-sourced shelf prices) so a 10000-record run still
has a price on each row.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from twextract.client import ExtractClient
from twextract.ipcheck import inspect_exit_ip
from twextract.username import Targeting

USE_CASE = "eCommerce & Price Monitoring"
DUMMYJSON_CATEGORIES_URL = "https://dummyjson.com/products/categories"
DUMMYJSON_CATEGORY_URL = "https://dummyjson.com/products/category/{slug}"
OPEN_PRICES_URL = "https://prices.openfoodfacts.org/api/v1/prices"
JSON_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "2extract-course/1.0 (educational category catalog scrape)",
}
STAR_MAP = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
STAR_LABELS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}
GENERIC_CATEGORY_TAGS = {
    "plant-based-foods-and-beverages",
    "plant-based-foods",
    "plant-based-beverages",
    "beverages",
    "foods",
    "snacks",
    "dairies",
    "fermented-foods",
    "fermented-milk-products",
}


def parse_price(text: str | None) -> tuple[str | None, float | None, str | None]:
    if text is None or text == "":
        return None, None, None
    raw = " ".join(str(text).split())
    currency = None
    if "£" in raw:
        currency = "GBP"
    elif "€" in raw:
        currency = "EUR"
    elif "$" in raw:
        currency = "USD"
    match = re.search(r"[\d]+\.[\d]+|[\d]+", raw.replace(",", ""))
    value = float(match.group(0)) if match else None
    return raw, value, currency


def format_money(value: Any, currency: str | None) -> tuple[str | None, float | None, str | None]:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None, None, None
    code = (currency or "").upper() or None
    symbol = CURRENCY_SYMBOLS.get(code or "")
    if symbol:
        raw = f"{symbol}{amount:.2f}"
    elif code:
        raw = f"{amount:.2f} {code}"
    else:
        raw = f"{amount:.2f}"
    return raw, amount, code


def parse_availability(text: str | None) -> tuple[str | None, bool | None, int | None]:
    if not text:
        return None, None, None
    raw = " ".join(str(text).split())
    match = re.search(r"(\d+)\s+available", raw, re.I)
    count = int(match.group(1)) if match else None
    lowered = raw.lower()
    if "out of stock" in lowered:
        in_stock = False
    elif "in stock" in lowered or "low stock" in lowered:
        in_stock = True
    else:
        in_stock = None
    return raw, in_stock, count


def parse_rating(classes: list[str]) -> tuple[str | None, int | None]:
    for name, value in STAR_MAP.items():
        if name in classes:
            return name, value
    return None, None


def rating_from_score(score: Any) -> tuple[str | None, int | None, float | None]:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None, None, None
    stars = max(1, min(5, int(round(value))))
    return STAR_LABELS[stars], stars, round(value, 2)


def parse_category_list(payload: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    items = payload if isinstance(payload, list) else []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            slug = item.strip()
            name = slug.replace("-", " ").title()
            url = DUMMYJSON_CATEGORY_URL.format(slug=slug)
        elif isinstance(item, dict):
            slug = str(item.get("slug") or item.get("name") or "").strip()
            name = str(item.get("name") or slug.replace("-", " ").title())
            url = str(item.get("url") or DUMMYJSON_CATEGORY_URL.format(slug=slug))
        else:
            continue
        if not slug or slug in seen:
            continue
        seen.add(slug)
        rows.append({"slug": slug, "name": name, "url": url})
    return rows


def product_from_dummyjson(item: dict[str, Any], *, listing_page: int = 1) -> dict[str, Any]:
    price, price_value, currency = format_money(item.get("price"), "USD")
    availability, in_stock, _count = parse_availability(item.get("availabilityStatus"))
    stock = item.get("stock")
    try:
        stock_count = int(stock) if stock is not None else None
    except (TypeError, ValueError):
        stock_count = None
    rating_label, rating_stars, rating_score = rating_from_score(item.get("rating"))
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    product_id = item.get("id")
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    name = item.get("title")
    return {
        "source": "dummyjson.com",
        "catalog": "DummyJSON store",
        "product_id": product_id,
        "product_name": name,
        "product_url": f"https://dummyjson.com/products/{product_id}" if product_id is not None else None,
        "listing_page": listing_page,
        "category": item.get("category"),
        "brand": item.get("brand") or None,
        "sku": item.get("sku"),
        "upc": meta.get("barcode"),
        "price": price,
        "price_value": price_value,
        "currency": currency,
        "discount_percentage": item.get("discountPercentage"),
        "availability": availability or item.get("availabilityStatus"),
        "in_stock": in_stock,
        "stock_count": stock_count,
        "rating": rating_label,
        "rating_value": rating_stars,
        "rating_score": rating_score,
        "product_type": "Product",
        "warranty": item.get("warrantyInformation"),
        "shipping": item.get("shippingInformation"),
        "return_policy": item.get("returnPolicy"),
        "tags": tags,
        "thumbnail": item.get("thumbnail"),
        "description": (item.get("description") or "")[:800] or None,
        "detail_url": f"https://dummyjson.com/products/{product_id}" if product_id is not None else None,
        "has_price": price_value is not None,
    }


def product_from_openprices(item: dict[str, Any], *, listing_page: int = 1) -> dict[str, Any] | None:
    if not isinstance(item, dict) or item.get("price") is None:
        return None
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    location = item.get("location") if isinstance(item.get("location"), dict) else {}
    name = " ".join(str(item.get("product_name") or product.get("product_name") or "").split())
    if not name:
        return None
    price, price_value, currency = format_money(item.get("price"), item.get("currency"))
    if price_value is None:
        return None
    code = str(item.get("product_code") or product.get("code") or "").strip()
    tags = product.get("categories_tags") if isinstance(product.get("categories_tags"), list) else []
    category = _leaf_category(tags) or _plain_tag(item.get("category_tag")) or "groceries"
    store = location.get("osm_brand") or location.get("osm_name")
    city = location.get("osm_address_city")
    country = location.get("osm_address_country_code") or location.get("osm_address_country")
    price_date = item.get("date")
    availability, in_stock = availability_from_shelf_price(
        store=store, city=city, country=country, price_date=price_date
    )
    url = f"https://world.openfoodfacts.org/product/{code}" if code else "https://prices.openfoodfacts.org/"
    observation_id = item.get("id")
    return {
        "source": "prices.openfoodfacts.org",
        "catalog": "Open Prices",
        "observation_id": observation_id,
        "product_id": code or observation_id,
        "product_name": name,
        "product_url": url,
        "listing_page": listing_page,
        "category": category,
        "brand": product.get("brands") or None,
        "sku": code or None,
        "upc": code or None,
        "price": price,
        "price_value": price_value,
        "currency": currency,
        "price_is_discounted": item.get("price_is_discounted"),
        "price_date": price_date,
        "availability": availability,
        "in_stock": in_stock,
        "stock_count": None,
        "quantity": product.get("quantity") or None,
        "stores": store,
        "store_city": location.get("osm_address_city"),
        "store_country": location.get("osm_address_country_code") or location.get("osm_address_country"),
        "product_type": "product",
        "tags": [_plain_tag(tag) for tag in tags[-6:]],
        "thumbnail": product.get("image_url"),
        "description": None,
        "detail_url": url,
        "has_price": True,
    }


def availability_from_shelf_price(
    *,
    store: str | None,
    city: str | None = None,
    country: str | None = None,
    price_date: str | None = None,
) -> tuple[str, bool]:
    """Open Prices has no warehouse count. A photographed shelf/receipt price means it was in stock there."""
    place_bits = [part for part in (store, city, country) if part]
    where = ", ".join(str(part) for part in place_bits) or "store"
    when = f" on {price_date}" if price_date else ""
    return f"In stock at {where}{when}", True


def enrich_openprices_availability(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("source") != "prices.openfoodfacts.org":
        return row
    availability, in_stock = availability_from_shelf_price(
        store=row.get("stores"),
        city=row.get("store_city"),
        country=row.get("store_country"),
        price_date=row.get("price_date"),
    )
    row["availability"] = availability
    row["in_stock"] = in_stock
    return row


def interleave_buckets(buckets: list[list[dict[str, Any]]], count: int) -> list[dict[str, Any]]:
    """Take one item from each category in turn so the sheet is mixed, not one department then the next."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    index = 0
    while len(rows) < count:
        progressed = False
        for bucket in buckets:
            if index >= len(bucket):
                continue
            item = bucket[index]
            key = product_identity_keys(item)
            progressed = True
            if not key or key & seen:
                continue
            seen.update(key)
            rows.append(item)
            if len(rows) >= count:
                return rows
        if not progressed:
            break
        index += 1
    return rows


def build_summary(rows: list[dict[str, Any]], *, exit_info: dict[str, Any], targeting: Targeting, session_id: str) -> list[dict[str, Any]]:
    priced = [row for row in rows if isinstance(row.get("price_value"), (int, float))]
    usd = [row for row in priced if row.get("currency") == "USD"]
    in_stock = sum(1 for row in rows if row.get("in_stock") is True)
    out_stock = sum(1 for row in rows if row.get("in_stock") is False)
    cheapest = min(usd, key=lambda row: row["price_value"]) if usd else {}
    dearest = max(usd, key=lambda row: row["price_value"]) if usd else {}
    categories = sorted({str(row.get("category")) for row in rows if row.get("category")})
    currencies = sorted({str(row.get("currency")) for row in priced if row.get("currency")})
    dummyjson_n = sum(1 for row in rows if row.get("source") == "dummyjson.com")
    openprices_n = sum(1 for row in rows if row.get("source") == "prices.openfoodfacts.org")
    usd_avg = round(sum(row["price_value"] for row in usd) / len(usd), 2) if usd else ""
    return [
        {"metric": "Use case", "value": USE_CASE},
        {"metric": "Products scraped", "value": len(rows)},
        {"metric": "Succeeded", "value": sum(1 for row in rows if row.get("ok"))},
        {"metric": "Rows with price", "value": len(priced)},
        {"metric": "Rows missing price", "value": len(rows) - len(priced)},
        {"metric": "Unique products", "value": unique_product_count(rows)},
        {"metric": "Categories covered", "value": len(categories)},
        {"metric": "Category list", "value": ", ".join(categories)},
        {"metric": "DummyJSON products", "value": dummyjson_n},
        {"metric": "Open Prices products", "value": openprices_n},
        {"metric": "Currencies", "value": ", ".join(currencies)},
        {"metric": "In stock", "value": in_stock},
        {"metric": "Out of stock", "value": out_stock},
        {"metric": "Average DummyJSON price (USD)", "value": usd_avg},
        {"metric": "Lowest USD price", "value": cheapest.get("price")},
        {"metric": "Lowest-priced USD product", "value": cheapest.get("product_name")},
        {"metric": "Highest USD price", "value": dearest.get("price")},
        {"metric": "Highest-priced USD product", "value": dearest.get("product_name")},
        {"metric": "Target country", "value": targeting.normalized().country},
        {"metric": "Sticky session", "value": session_id},
        {"metric": "Exit IP", "value": exit_info.get("ip")},
        {"metric": "Exit country", "value": exit_info.get("country")},
        {"metric": "Exit region", "value": exit_info.get("region")},
        {"metric": "Exit city", "value": exit_info.get("city")},
        {"metric": "Exit ISP", "value": exit_info.get("org")},
        {"metric": "Source", "value": "https://dummyjson.com/products/categories + https://prices.openfoodfacts.org"},
    ]


def run_price_monitor(
    client: ExtractClient,
    *,
    country: str = "us",
    count: int = 10000,
    pause_seconds: float = 0.25,
    details: bool = True,
    dummyjson_only: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if count < 1:
        raise ValueError("count must be at least 1")
    session_id = uuid.uuid4().hex[:12]
    session_minutes = min(60, max(20, count // 40 + 15))
    targeting = Targeting(country=country, session=session_id, time_minutes=session_minutes)
    collected_at = datetime.now(timezone.utc).isoformat()
    exit_info: dict[str, Any] = {}
    try:
        exit_info = inspect_exit_ip(client, targeting)
    except Exception as exc:
        exit_info = {"error": str(exc)}

    print(
        f"Sticky US session {session_id} for {session_minutes} min. "
        f"Walking store departments for {count} mixed-category products with prices."
    )
    listings = collect_catalog(
        client,
        targeting=targeting,
        count=count,
        pause_seconds=pause_seconds,
        include_openprices=details and not dummyjson_only,
    )
    if len(listings) < count:
        print(f"Warning: catalogs only returned {len(listings)} unique products (requested {count}).")

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(listings, start=1):
        has_price = isinstance(item.get("price_value"), (int, float))
        row: dict[str, Any] = {
            "use_case": USE_CASE,
            "row_number": index,
            "collected_at": collected_at,
            "session_id": session_id,
            "target_country": targeting.normalized().country,
            "ok": bool(item.get("product_name") and has_price),
            **item,
            "has_price": has_price,
            "exit": exit_info,
        }
        rows.append(row)
        if index % 100 == 0 or index == len(listings):
            priced = sum(1 for item_row in rows if item_row.get("has_price"))
            print(
                f"[{index}/{count}] {priced}/{index} have a price | "
                f"{row.get('category') or '-'} | {row.get('product_name') or '-'} | {row.get('price') or '-'}"
            )
            _checkpoint(rows, exit_info, targeting, session_id)

    summary = build_summary(rows, exit_info=exit_info, targeting=targeting, session_id=session_id)
    missing = sum(1 for row in rows if not row.get("has_price"))
    if missing:
        print(f"Warning: {missing} rows still have no price.")
    _checkpoint(rows, exit_info, targeting, session_id)
    return rows, summary


def collect_catalog(
    client: ExtractClient,
    *,
    targeting: Targeting,
    count: int,
    pause_seconds: float,
    include_openprices: bool,
) -> list[dict[str, Any]]:
    try:
        dummy_buckets = _collect_dummyjson(client, targeting, pause_seconds)
    except Exception as exc:
        print(f"DummyJSON catalog failed: {exc}")
        dummy_buckets = []
    dummy_rows = interleave_buckets(dummy_buckets, count)
    print(f"DummyJSON: {sum(len(bucket) for bucket in dummy_buckets)} products across {len(dummy_buckets)} departments.")
    dummy_rows = drop_duplicate_products(dummy_rows)[:count]
    if len(dummy_rows) >= count or not include_openprices:
        return dummy_rows[:count]

    remaining = count - len(dummy_rows)
    print(f"Filling {remaining} more priced rows from Open Prices (skipping anything already in DummyJSON).")
    seen: set[str] = set()
    for row in dummy_rows:
        seen.update(product_identity_keys(row))
    open_buckets = _collect_openprices(client, targeting, remaining, pause_seconds, seen)
    open_rows = interleave_buckets(open_buckets, remaining)
    return drop_duplicate_products(dummy_rows + open_rows)[:count]


def _collect_dummyjson(
    client: ExtractClient,
    targeting: Targeting,
    pause_seconds: float,
) -> list[list[dict[str, Any]]]:
    payload = _get_json(client, DUMMYJSON_CATEGORIES_URL, targeting)
    categories = parse_category_list(payload)
    if not categories:
        raise RuntimeError("DummyJSON returned no product categories.")
    print(f"DummyJSON departments ({len(categories)}): " + ", ".join(item["slug"] for item in categories))
    buckets: list[list[dict[str, Any]]] = []
    for index, category in enumerate(categories, start=1):
        url = f"{DUMMYJSON_CATEGORY_URL.format(slug=category['slug'])}?limit=0"
        try:
            body = _get_json(client, url, targeting)
            products = body.get("products") if isinstance(body, dict) else []
            bucket = [
                product_from_dummyjson(item, listing_page=index)
                for item in products
                if isinstance(item, dict)
            ]
            buckets.append(bucket)
            print(f"  {category['slug']}: {len(bucket)} products")
        except Exception as exc:
            print(f"  {category['slug']}: FAIL {exc}")
            buckets.append([])
        time.sleep(pause_seconds)
    return buckets


def _collect_openprices(
    client: ExtractClient,
    targeting: Targeting,
    remaining: int,
    pause_seconds: float,
    seen: set[str],
) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    page = 1
    collected = 0
    empty_pages = 0
    max_pages = max(40, remaining // 80 + 15)
    while collected < remaining and page <= max_pages:
        query = urlencode({"size": 100, "page": page, "order_by": "-created"})
        url = f"{OPEN_PRICES_URL}?{query}"
        try:
            body = _get_json(client, url, targeting, headers=JSON_HEADERS)
            items = body.get("items") if isinstance(body, dict) else []
            added = 0
            for item in items:
                row = product_from_openprices(item, listing_page=page)
                if not row or is_duplicate_product(row, seen):
                    continue
                grouped[str(row.get("category") or "groceries")].append(row)
                collected += 1
                added += 1
                if collected >= remaining:
                    break
            print(f"  Open Prices page {page}: +{added} priced products ({collected}/{remaining})")
            empty_pages = empty_pages + 1 if added == 0 else 0
            if not items or empty_pages >= 3:
                break
        except Exception as exc:
            print(f"  Open Prices page {page}: FAIL {exc}")
            empty_pages += 1
            if empty_pages >= 3:
                break
        page += 1
        time.sleep(pause_seconds)
    return list(grouped.values())


def _get_json(
    client: ExtractClient,
    url: str,
    targeting: Targeting,
    *,
    timeout: int = 45,
    headers: dict[str, str] | None = None,
) -> Any:
    response = client.get(url, targeting=targeting, timeout=timeout, headers=headers)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Expected JSON from {url}") from exc


def product_identity_keys(item: dict[str, Any]) -> set[str]:
    """Skip the same DummyJSON product twice. Open Prices rows are unique per shelf observation."""
    keys: set[str] = set()
    obs = _norm_token(item.get("observation_id"))
    if obs:
        keys.add(f"obs:{obs}")
        return keys
    for field in ("upc", "sku"):
        token = _norm_token(item.get(field))
        if token:
            keys.add(f"code:{token}")
    for field in ("product_url", "detail_url"):
        token = _norm_token(item.get(field)).rstrip("/")
        if token:
            keys.add(f"url:{token}")
    name = _norm_token(item.get("product_name"))
    for brand in _brand_tokens(item.get("brand")):
        if name:
            keys.add(f"named:{brand}|{name}")
    return keys


def is_duplicate_product(item: dict[str, Any], seen: set[str]) -> bool:
    keys = product_identity_keys(item)
    if not keys:
        return False
    if keys & seen:
        return True
    seen.update(keys)
    return False


def drop_duplicate_products(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        if is_duplicate_product(row, seen):
            skipped += 1
            continue
        unique.append(row)
    if skipped:
        print(f"Removed {skipped} duplicate product(s).")
    for index, row in enumerate(unique, start=1):
        row["row_number"] = index
    return unique


def unique_product_count(rows: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    count = 0
    for row in rows:
        keys = product_identity_keys(row)
        if keys & seen:
            continue
        seen.update(keys)
        count += 1
    return count


def _norm_token(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _brand_tokens(value: Any) -> list[str]:
    text = str(value or "")
    parts = [part.strip() for part in text.replace("/", ",").replace("|", ",").split(",")]
    tokens = [_norm_token(part) for part in parts]
    return [token for token in tokens if token]


def _plain_tag(tag: Any) -> str:
    text = str(tag or "")
    if ":" in text:
        text = text.split(":", 1)[1]
    return text.replace("-", " ").strip()


def _leaf_category(tags: list[Any]) -> str | None:
    specific = [tag for tag in tags if _plain_tag(tag).replace(" ", "-") not in GENERIC_CATEGORY_TAGS]
    chosen = specific[-1] if specific else (tags[-1] if tags else None)
    label = _plain_tag(chosen)
    return label.replace(" ", "-") if label else None


def _checkpoint(
    rows: list[dict[str, Any]],
    exit_info: dict[str, Any],
    targeting: Targeting,
    session_id: str,
) -> None:
    from twextract.excel_export import write_ecommerce_excel
    from twextract.geo_scrape import write_json

    summary = build_summary(rows, exit_info=exit_info, targeting=targeting, session_id=session_id)
    write_json("ecommerce_results.json", {"summary": summary, "products": rows})
    ok_count = sum(1 for row in rows if row.get("ok"))
    priced = sum(1 for row in rows if row.get("has_price"))
    try:
        write_ecommerce_excel(rows, summary)
        print(f"Checkpoint saved: {ok_count} ok / {priced} priced / {len(rows)} rows -> data/output/eCommerce.xlsx")
    except OSError as exc:
        print(f"JSON saved ({ok_count}/{len(rows)}). Close Excel if eCommerce.xlsx is open: {exc}")
    except Exception as exc:
        print(f"JSON saved ({ok_count}/{len(rows)}). Excel checkpoint skipped: {exc}")
