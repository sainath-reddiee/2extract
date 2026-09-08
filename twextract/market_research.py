"""Market Research through a 2extract residential proxy.

Use case from https://docs.2extract.com/proxy-products/residential/introduction-use-cases.md

Collect public data to analyze market trends, review sentiment, and gather
business intelligence at scale. Sources are Hacker News (discussion trends
and comment sentiment) and Open Food Facts (brand / category intelligence).
This is not DummyJSON, not the eCommerce price catalog, and not geo/address.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

from twextract.client import ExtractClient
from twextract.ipcheck import inspect_exit_ip
from twextract.username import Targeting

USE_CASE = "Market Research"
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
OFF_SEARCH_URL = "https://world.openfoodfacts.org/api/v2/search"
OFF_FIELDS = (
    "code,product_name,brands,categories_tags,nutriscore_grade,"
    "ecoscore_grade,countries_tags,unique_scans_n,last_modified_t"
)
JSON_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "2extract-course/1.0 (educational market research scrape)",
}
HTML_RE = re.compile(r"<[^>]+>")
HN_TOPICS = (
    ("", "story", "trend"),
    ("retail", "story", "trend"),
    ("inflation", "story", "trend"),
    ("earnings", "story", "intelligence"),
    ("startup", "story", "trend"),
    ("", "comment", "sentiment"),
)


def strip_html(value: Any) -> str:
    text = HTML_RE.sub(" ", str(value or ""))
    return " ".join(text.split())


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: drop_empty(child) for key, child in value.items() if child not in (None, "")}
    return value


def sentiment_from_engagement(score: Any, comments: Any = None) -> str:
    try:
        points = float(score)
    except (TypeError, ValueError):
        points = 0.0
    try:
        extra = float(comments or 0)
    except (TypeError, ValueError):
        extra = 0.0
    buzz = points + extra * 0.25
    if buzz >= 100:
        return "strong_positive"
    if buzz >= 20:
        return "positive"
    if buzz >= 5:
        return "neutral"
    if buzz > 0:
        return "low"
    return "unscored"


def nutriscore_sentiment(grade: Any) -> str:
    letter = _text(grade).lower()
    if letter in {"a", "b"}:
        return "positive"
    if letter == "c":
        return "mixed"
    if letter in {"d", "e"}:
        return "negative"
    return "unscored"


def publisher_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or "ycombinator.com" in host or "hn.algolia.com" in host:
        return "Y Combinator"
    return host


def _plain_tag(tag: Any) -> str:
    text = str(tag or "")
    if ":" in text:
        text = text.split(":", 1)[1]
    return text.replace("-", " ").strip()


def _leaf_category(tags: list[Any]) -> str:
    cleaned = [_plain_tag(tag) for tag in tags if _plain_tag(tag)]
    return cleaned[-1] if cleaned else "groceries"


def finalize_record(row: dict[str, Any], *, observed_at: str = "") -> dict[str, Any]:
    """Every research row keeps the same filled columns so Excel is not sparse."""
    title = _text(row.get("title"))
    body = _text(row.get("body"))
    if not title:
        title = (body[:80] + "…") if len(body) > 80 else (body or "Untitled")
    if not body:
        body = title
    score = row.get("score")
    comments = row.get("comment_count")
    views = row.get("views")
    parent = row.get("parent_id")
    tags = row.get("tags") if isinstance(row.get("tags"), list) else []
    topic = _text(row.get("topic")) or _text(row.get("category")) or "general"
    return {
        "source": _text(row.get("source")) or "unknown",
        "catalog": _text(row.get("catalog")) or _text(row.get("source")) or "unknown",
        "record_type": _text(row.get("record_type")) or "intelligence",
        "topic": topic,
        "category": _text(row.get("category")) or topic,
        "brand": _text(row.get("brand")) or "unbranded",
        "record_id": _text(row.get("record_id")) or title,
        "title": title,
        "body": body,
        "author": _text(row.get("author")) or "unknown",
        "score": _int(score, 0) if score is not None else 0,
        "rating_label": _text(row.get("rating_label")) or str(score if score is not None else "unrated"),
        "comment_count": _int(comments, 0),
        "views": _int(views, 0),
        "sentiment": _text(row.get("sentiment")) or "unscored",
        "published_at": _text(row.get("published_at")) or _text(observed_at) or "not provided by source",
        "url": _text(row.get("url")),
        "parent_id": "" if parent in (None, "") else parent,
        "tags": [str(tag) for tag in tags if tag not in (None, "")],
    }


def record_from_openfoodfacts(product: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(product, dict):
        return None
    code = _text(product.get("code"))
    title = _text(product.get("product_name"))
    if not code or not title:
        return None
    brand = _text(product.get("brands")).split(",")[0].strip() or "unbranded"
    tags = product.get("categories_tags") if isinstance(product.get("categories_tags"), list) else []
    category = _leaf_category(tags)
    nutriscore = _text(product.get("nutriscore_grade")).upper() or "unknown"
    ecoscore = _text(product.get("ecoscore_grade")).upper() or "unknown"
    countries = product.get("countries_tags") if isinstance(product.get("countries_tags"), list) else []
    markets = [_plain_tag(tag) for tag in countries if _plain_tag(tag)]
    scans = _int(product.get("unique_scans_n"), 0)
    modified = product.get("last_modified_t")
    published = ""
    if isinstance(modified, (int, float)) and modified > 0:
        published = datetime.fromtimestamp(modified, tz=timezone.utc).isoformat()
    market_text = ", ".join(markets[:8]) if markets else "unspecified markets"
    body = (
        f"Nutri-Score {nutriscore}. Eco-Score {ecoscore}. "
        f"Sold in {market_text}. Scan popularity {scans}."
    )
    return finalize_record(
        {
            "source": "world.openfoodfacts.org",
            "catalog": "Open Food Facts",
            "record_type": "intelligence",
            "topic": category,
            "category": category,
            "brand": brand,
            "record_id": f"off-{code}",
            "title": title,
            "body": body,
            "author": "Open Food Facts contributors",
            "score": scans,
            "rating_label": f"Nutri-Score {nutriscore}",
            "comment_count": len(markets),
            "views": scans,
            "sentiment": nutriscore_sentiment(nutriscore),
            "published_at": published,
            "url": f"https://world.openfoodfacts.org/product/{code}",
            "parent_id": code,
            "tags": [_plain_tag(tag) for tag in tags[-6:]],
        }
    )


def record_from_hn(hit: dict[str, Any], *, record_type: str, topic: str) -> dict[str, Any] | None:
    if not isinstance(hit, dict):
        return None
    object_id = hit.get("objectID")
    title = _text(hit.get("title")) or _text(hit.get("story_title"))
    body = strip_html(hit.get("comment_text") or hit.get("story_text") or "")
    url = _text(hit.get("url")) or _text(hit.get("story_url")) or (
        f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""
    )
    if not title and not body:
        return None
    if not body:
        body = f"{title}. Source: {url}".strip() if url else title
    if not title:
        title = body[:80]
    points = hit.get("points")
    comments = hit.get("num_comments")
    tags = hit.get("_tags") if isinstance(hit.get("_tags"), list) else []
    kind = "comment" if "comment" in tags else "story"
    parent = hit.get("parent_id") or hit.get("story_id")
    return finalize_record(
        {
            "source": "hn.algolia.com",
            "catalog": "Hacker News",
            "record_type": record_type,
            "topic": topic or kind,
            "category": topic or kind,
            "brand": publisher_from_url(url),
            "record_id": f"hn-{kind}-{object_id}",
            "title": title,
            "body": body,
            "author": _text(hit.get("author")) or "unknown",
            "score": points,
            "rating_label": f"{_int(points)} points",
            "comment_count": comments,
            "views": comments,
            "sentiment": sentiment_from_engagement(points, comments),
            "published_at": _text(hit.get("created_at")),
            "url": url or f"https://news.ycombinator.com/item?id={object_id}",
            "parent_id": parent if parent is not None else "",
            "tags": [str(tag) for tag in tags[:8] if isinstance(tag, str) and "author_" not in tag],
        }
    )


def record_identity_keys(item: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    record_id = " ".join(str(item.get("record_id") or "").strip().lower().split())
    if record_id:
        keys.add(f"id:{record_id}")
    url = " ".join(str(item.get("url") or "").strip().lower().split()).rstrip("/")
    if url:
        keys.add(f"url:{url}")
    return keys


def is_duplicate_record(item: dict[str, Any], seen: set[str]) -> bool:
    keys = record_identity_keys(item)
    if not keys:
        return False
    if keys & seen:
        return True
    seen.update(keys)
    return False


def drop_duplicate_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        if is_duplicate_record(row, seen):
            skipped += 1
            continue
        unique.append(row)
    if skipped:
        print(f"Removed {skipped} duplicate research row(s).")
    for index, row in enumerate(unique, start=1):
        row["row_number"] = index
    return unique


def interleave_buckets(buckets: list[list[dict[str, Any]]], count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    index = 0
    while len(rows) < count:
        progressed = False
        for bucket in buckets:
            if index >= len(bucket):
                continue
            item = bucket[index]
            progressed = True
            key = record_identity_keys(item)
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


def build_summary(
    rows: list[dict[str, Any]],
    *,
    exit_info: dict[str, Any],
    targeting: Targeting,
    session_id: str,
) -> list[dict[str, Any]]:
    types = sorted({str(row.get("record_type")) for row in rows if row.get("record_type")})
    topics = sorted({str(row.get("topic")) for row in rows if row.get("topic")})
    sentiments = sorted({str(row.get("sentiment")) for row in rows if row.get("sentiment")})
    hn_n = sum(1 for row in rows if row.get("source") == "hn.algolia.com")
    off_n = sum(1 for row in rows if row.get("source") == "world.openfoodfacts.org")
    return [
        {"metric": "Use case", "value": USE_CASE},
        {"metric": "Records scraped", "value": len(rows)},
        {"metric": "Succeeded", "value": sum(1 for row in rows if row.get("ok"))},
        {"metric": "Hacker News rows", "value": hn_n},
        {"metric": "Open Food Facts rows", "value": off_n},
        {"metric": "Record types", "value": ", ".join(types)},
        {"metric": "Topics", "value": ", ".join(topics[:40])},
        {"metric": "Sentiment labels", "value": ", ".join(sentiments)},
        {"metric": "Target country", "value": targeting.normalized().country},
        {"metric": "Sticky session", "value": session_id},
        {"metric": "Exit IP", "value": exit_info.get("ip")},
        {"metric": "Exit country", "value": exit_info.get("country")},
        {"metric": "Exit city", "value": exit_info.get("city")},
        {"metric": "Source", "value": "news.ycombinator.com via hn.algolia.com + world.openfoodfacts.org"},
    ]


def run_market_research(
    client: ExtractClient,
    *,
    country: str = "us",
    count: int = 10000,
    pause_seconds: float = 0.2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if count < 1:
        raise ValueError("count must be at least 1")
    session_id = uuid.uuid4().hex[:12]
    session_minutes = min(60, max(20, count // 80 + 15))
    targeting = Targeting(country=country, session=session_id, time_minutes=session_minutes)
    collected_at = datetime.now(timezone.utc).isoformat()
    exit_info: dict[str, Any] = {}
    try:
        exit_info = drop_empty(inspect_exit_ip(client, targeting))
    except Exception as exc:
        exit_info = {"error": str(exc)}

    print(
        f"Sticky US session {session_id} for {session_minutes} min. "
        f"Collecting {count} public market-research rows (trends, sentiment, intelligence)."
    )
    listings = collect_research(
        client,
        targeting=targeting,
        count=count,
        pause_seconds=pause_seconds,
    )
    if len(listings) < count:
        print(f"Warning: catalogs only returned {len(listings)} unique research rows (requested {count}).")

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(listings, start=1):
        row: dict[str, Any] = {
            "use_case": USE_CASE,
            "row_number": index,
            "collected_at": collected_at,
            "session_id": session_id,
            "target_country": targeting.normalized().country,
            "ok": bool(item.get("record_id") and (item.get("title") or item.get("body"))),
            **item,
            "exit": exit_info,
        }
        rows.append(row)
        if index % 100 == 0 or index == len(listings):
            print(
                f"[{index}/{count}] {row.get('record_type') or '-'} | "
                f"{row.get('topic') or '-'} | {(row.get('title') or row.get('body') or '-')[:80]}"
            )
            _checkpoint(rows, exit_info, targeting, session_id)

    summary = build_summary(rows, exit_info=exit_info, targeting=targeting, session_id=session_id)
    _checkpoint(rows, exit_info, targeting, session_id)
    return rows, summary


def collect_research(
    client: ExtractClient,
    *,
    targeting: Targeting,
    count: int,
    pause_seconds: float,
) -> list[dict[str, Any]]:
    hn_target = max(1, (count + 1) // 2)
    off_target = max(0, count - hn_target)
    buckets: list[list[dict[str, Any]]] = []
    seen: set[str] = set()

    print(f"Collecting up to {hn_target} Hacker News rows (trends and sentiment).")
    try:
        hn_buckets = _collect_hn(client, targeting, hn_target, pause_seconds, seen)
        buckets.extend(hn_buckets)
    except Exception as exc:
        print(f"Hacker News failed: {exc}")

    hn_count = sum(len(bucket) for bucket in buckets)
    need_off = max(off_target, count - hn_count)
    if need_off > 0:
        print(f"Collecting up to {need_off} Open Food Facts brand-intelligence rows.")
        try:
            off_rows = _collect_openfoodfacts(client, targeting, need_off, pause_seconds, seen)
            if off_rows:
                buckets.append(off_rows)
        except Exception as exc:
            print(f"Open Food Facts failed: {exc}")

    mixed = interleave_buckets(buckets, count)
    mixed = drop_duplicate_records(mixed)
    if len(mixed) < count:
        remaining = count - len(mixed)
        print(f"Filling {remaining} more rows from Hacker News.")
        extra = _collect_hn(client, targeting, remaining, pause_seconds, seen)
        mixed = drop_duplicate_records(mixed + interleave_buckets(extra, remaining))
    return mixed[:count]


def _payload_list(payload: Any, key: str) -> list[dict[str, Any]]:
    items = payload.get(key) if isinstance(payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _collect_openfoodfacts(
    client: ExtractClient,
    targeting: Targeting,
    remaining: int,
    pause_seconds: float,
    seen: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    empty_pages = 0
    max_pages = max(20, remaining // 80 + 5)
    while len(rows) < remaining and page <= max_pages:
        params = {"page": page, "page_size": 100, "fields": OFF_FIELDS, "sort_by": "unique_scans_n"}
        url = f"{OFF_SEARCH_URL}?{urlencode(params)}"
        try:
            body = _get_json(client, url, targeting, headers=JSON_HEADERS)
            products = _payload_list(body, "products")
            added = 0
            for product in products:
                row = record_from_openfoodfacts(product)
                if not row or is_duplicate_record(row, seen):
                    continue
                rows.append(row)
                added += 1
                if len(rows) >= remaining:
                    break
            print(f"  Open Food Facts page {page}: +{added} ({len(rows)}/{remaining})")
            empty_pages = empty_pages + 1 if added == 0 else 0
            if not products or empty_pages >= 3:
                break
        except Exception as exc:
            print(f"  Open Food Facts page {page}: FAIL {exc}")
            empty_pages += 1
            if empty_pages >= 3:
                break
        page += 1
        time.sleep(pause_seconds)
    return rows


def _collect_hn(
    client: ExtractClient,
    targeting: Targeting,
    remaining: int,
    pause_seconds: float,
    seen: set[str],
) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    collected = 0
    for query, tags, record_type in HN_TOPICS:
        if collected >= remaining:
            break
        page = 0
        empty_pages = 0
        topic_label = query or ("hn-comments" if tags == "comment" else "hn-stories")
        while collected < remaining and page < 50:
            params: dict[str, Any] = {"tags": tags, "hitsPerPage": 100, "page": page}
            if query:
                params["query"] = query
            url = f"{HN_SEARCH_URL}?{urlencode(params)}"
            try:
                body = _get_json(client, url, targeting, headers=JSON_HEADERS)
                hits = body.get("hits") if isinstance(body, dict) else []
                added = 0
                for hit in hits:
                    row = record_from_hn(hit, record_type=record_type, topic=topic_label)
                    if not row or is_duplicate_record(row, seen):
                        continue
                    grouped[str(row.get("record_type") or record_type)].append(row)
                    collected += 1
                    added += 1
                    if collected >= remaining:
                        break
                print(
                    f"  HN {topic_label} page {page}: +{added} "
                    f"({collected}/{remaining})"
                )
                empty_pages = empty_pages + 1 if added == 0 else 0
                nb_pages = body.get("nbPages") if isinstance(body, dict) else None
                if not hits or empty_pages >= 3:
                    break
                if isinstance(nb_pages, int) and page + 1 >= nb_pages:
                    break
            except Exception as exc:
                print(f"  HN {topic_label} page {page}: FAIL {exc}")
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


def _checkpoint(
    rows: list[dict[str, Any]],
    exit_info: dict[str, Any],
    targeting: Targeting,
    session_id: str,
) -> None:
    from twextract.excel_export import write_market_research_excel
    from twextract.geo_scrape import write_json

    summary = build_summary(rows, exit_info=exit_info, targeting=targeting, session_id=session_id)
    write_json("market_research_results.json", {"summary": summary, "rows": rows})
    ok_count = sum(1 for row in rows if row.get("ok"))
    try:
        write_market_research_excel(rows, summary)
        print(
            f"Checkpoint saved: {ok_count} ok / {len(rows)} rows -> data/output/market_research.xlsx"
        )
    except OSError as exc:
        print(f"JSON saved ({len(rows)}). Close Excel if market_research.xlsx is open: {exc}")
    except Exception as exc:
        print(f"JSON saved ({len(rows)}). Excel checkpoint skipped: {exc}")
