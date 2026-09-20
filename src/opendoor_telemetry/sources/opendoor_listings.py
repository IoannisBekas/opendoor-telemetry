"""Workstream 1.4 -- Opendoor property telemetry from public web endpoints.

Replaces paid aggregator feeds (Parcl Labs / Attom) with Opendoor's own
published sitemap plus the structured data already embedded in each
property page.

WHY NO BROWSER IS NEEDED
------------------------
The initial design called for Playwright. That turned out to be
unnecessary: Opendoor server-renders both a JSON-LD block and a Next.js
`__NEXT_DATA__` payload into the HTML. A verified fetch of a Charlotte
listing returned, with no JavaScript executed:

    daysOnMarket: 128, listPrice: 650000, buyDirectPrice: 643500,
    listingState: ON_THE_MARKET, latitude/longitude, sqFtTotalLiving,
    pricePerSqFt, yearBuilt, bedrooms, bathrooms, listingHistory[]

So this module is plain httpx + a regex for the two script tags. That
removes a headless-Chromium dependency and roughly an order of magnitude
of compute per sweep.

POLITENESS
----------
robots.txt (fetched 2026-09-20) publishes the sitemaps we read and allows
/properties/ and /homes/. It disallows /api/ (except /api/agent/v1/), which
PoliteClient enforces structurally -- a blocked path raises rather than
fetching. Default cadence is one full sweep per day at 1 req/s.

Opendoor also declares `Content-Signal: ai-train=no`. This pipeline does
quantitative market analysis and trains nothing, which is consistent with
that signal; see README.

THE PRICE-CUT GOTCHA
--------------------
`listingHistory[].originalListPriceCents` is null while a listing is
active -- it is only populated on historical SOLD rows. Price-cut depth
therefore CANNOT be read off the page; it has to be diffed against our own
earliest observation. That is why listing_snapshots is append-only and
listing_dim carries first_list_price.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Iterator
from uuid import UUID

from ..config import get_settings
from ..db import connect, ingest_run, record_exception, upsert
from ..http import opendoor_client

log = logging.getLogger(__name__)

SITEMAP_INDEX = "https://www.opendoor.com/sitemaps/sitemap.xml"
LISTINGS_SITEMAP = "https://www.opendoor.com/sitemaps/listings.xml"
HOMES_SITEMAP = "https://www.opendoor.com/sitemaps/homes.xml"

NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)
LD_JSON_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)
URL_RE = re.compile(r"<url>\s*<loc>(.*?)</loc>(?:\s*<lastmod>(.*?)</lastmod>)?", re.S)
AID_RE = re.compile(r"/aid_([0-9a-fA-F-]{36})")

DIM_COLUMNS = [
    "address_token", "slug", "street", "city", "state", "zip", "msa_key",
    "latitude", "longitude", "year_built", "bedrooms", "bathrooms",
    "sqft_living", "sqft_lot", "dwelling_type", "first_seen", "last_seen",
    "first_list_price",
]
SNAP_COLUMNS = [
    "snapshot_date", "address_token", "list_price", "buy_direct_price",
    "buy_direct_savings", "days_on_market", "listing_state", "display_badge",
    "price_per_sqft", "est_monthly_payment", "http_status",
]


# --------------------------------------------------------------------- #
# sitemap
# --------------------------------------------------------------------- #
def _normalize_loc(loc: str) -> str:
    """Percent-encode a literal '#' in a sitemap URL path.

    Opendoor publishes unit numbers unescaped, e.g.
        /properties/4747-Puritan-Cir-#-523-Tampa-FL-33617/aid_...
    An HTTP client reads that '#' as the fragment delimiter and requests only
    '/properties/4747-Puritan-Cir-', which 404s. Encoding it to %23 returns
    200. Verified against the live site: 8 of 15 sweep failures were this.
    """
    scheme, sep, rest = loc.partition("://")
    if not sep:
        return loc.replace("#", "%23")
    return scheme + sep + rest.replace("#", "%23")


def fetch_sitemap(url: str = LISTINGS_SITEMAP) -> list[dict[str, str]]:
    """Return [{url, lastmod, address_token}] for every listing in the sitemap."""
    with opendoor_client() as client:
        resp = client.get(url)
        resp.raise_for_status()
        xml = resp.text

    out: list[dict[str, str]] = []
    for loc, lastmod in URL_RE.findall(xml):
        loc = _normalize_loc(loc.strip())
        m = AID_RE.search(loc)
        out.append(
            {
                "url": loc,
                "lastmod": (lastmod or "").strip(),
                "address_token": m.group(1).lower() if m else "",
            }
        )
    log.info("sitemap %s: %d entries", url.rsplit("/", 1)[-1], len(out))
    return out


def fetch_market_slugs() -> list[str]:
    """Market landing pages from homes.xml, e.g. 'charlotte', 'phoenix'."""
    entries = fetch_sitemap(HOMES_SITEMAP)
    slugs = []
    for e in entries:
        tail = e["url"].rstrip("/").rsplit("/homes/", 1)
        if len(tail) == 2 and tail[1]:
            slugs.append(tail[1])
    return sorted(set(slugs))


# --------------------------------------------------------------------- #
# property page extraction
# --------------------------------------------------------------------- #
def extract_property(html: str) -> dict[str, Any]:
    """Pull the property object from __NEXT_DATA__, falling back to JSON-LD."""
    prop: dict[str, Any] = {}

    m = NEXT_DATA_RE.search(html)
    if m:
        try:
            payload = json.loads(m.group(1))
            prop = payload.get("props", {}).get("pageProps", {}).get("property", {}) or {}
        except json.JSONDecodeError as exc:
            log.debug("__NEXT_DATA__ decode failed: %s", exc)

    if prop:
        return prop

    # Fallback: JSON-LD carries price, geo, beds/baths but no daysOnMarket.
    for block in LD_JSON_RE.findall(html):
        try:
            ld = json.loads(block)
        except json.JSONDecodeError:
            continue
        types = ld.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if not any("Residence" in t or "Product" in t for t in types):
            continue
        addr = ld.get("address", {}) or {}
        geo = ld.get("geo", {}) or {}
        offers = ld.get("offers", {}) or {}
        return {
            "street": addr.get("streetAddress"),
            "city": addr.get("addressLocality"),
            "state": addr.get("addressRegion"),
            "zip": addr.get("postalCode"),
            "latitude": geo.get("latitude"),
            "longitude": geo.get("longitude"),
            "listPrice": offers.get("price"),
            "bedrooms": ld.get("numberOfBedrooms"),
            "bathrooms": ld.get("numberOfBathroomsTotal"),
            "yearBuilt": ld.get("yearBuilt"),
            "_source": "json-ld",
        }
    return {}


def _as_int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_rows(
    prop: dict[str, Any], token: str, today: date, status: int
) -> tuple[tuple | None, tuple | None]:
    """Map a property payload to (dim_row, snapshot_row)."""
    settings = get_settings()
    if not token:
        return None, None
    try:
        tok = str(UUID(token))
    except ValueError:
        return None, None

    city = prop.get("city")
    state = prop.get("state")
    lat = _as_float(prop.get("latitude"))
    lon = _as_float(prop.get("longitude"))
    # Geographic assignment, not city-name matching: most Opendoor inventory
    # sits in suburbs whose names appear in no CBSA title.
    market = settings.market_for_point(lat, lon)

    list_price = _as_float(prop.get("listPrice"))

    dim = (
        tok,
        prop.get("slug"),
        prop.get("street"),
        city,
        state,
        prop.get("zip"),
        market.key if market else None,
        lat,
        lon,
        _as_int(prop.get("yearBuilt")),
        _as_int(prop.get("bedrooms")),
        _as_float(prop.get("bathrooms")),
        _as_int(prop.get("sqFtTotalLiving")),
        _as_int(prop.get("sqFtLot")),
        prop.get("dwellingType"),
        today,           # first_seen  (kept by the upsert below)
        today,           # last_seen
        list_price,      # first_list_price (kept by the upsert below)
    )

    snap = (
        today,
        tok,
        list_price,
        _as_float(prop.get("buyDirectPrice")),
        _as_float(prop.get("buyDirectSavings")),
        _as_int(prop.get("daysOnMarket")),
        prop.get("listingState"),
        prop.get("displayBadge"),
        _as_float(prop.get("pricePerSqFt")),
        _as_float(prop.get("estimatedMonthlyPayment")),
        status,
    )
    return dim, snap


# --------------------------------------------------------------------- #
# sweep
# --------------------------------------------------------------------- #
def sweep(limit: int | None = None, *, skip_unchanged: bool = False) -> dict[str, Any]:
    """Fetch listings and return the rows to persist (no DB writes here)."""
    entries = fetch_sitemap()
    if limit:
        entries = entries[:limit]

    today = date.today()
    dims: list[tuple] = []
    snaps: list[tuple] = []
    failures: list[tuple[str, str]] = []
    seen_tokens: list[str] = []

    with opendoor_client() as client:
        for i, e in enumerate(entries, 1):
            if not e["address_token"]:
                failures.append((e["url"], "no aid_ token in URL"))
                continue
            try:
                resp = client.get(e["url"])
            except PermissionError as exc:
                failures.append((e["url"], str(exc)))
                continue

            if resp.status_code != 200:
                failures.append((e["url"], f"HTTP {resp.status_code}"))
                continue

            prop = extract_property(resp.text)
            if not prop:
                failures.append((e["url"], "no __NEXT_DATA__ or JSON-LD payload"))
                continue

            dim, snap = to_rows(prop, e["address_token"], today, resp.status_code)
            if dim and snap:
                dims.append(dim)
                snaps.append(snap)
                seen_tokens.append(dim[0])

            if i % 250 == 0:
                log.info("swept %d/%d listings", i, len(entries))

    log.info("sweep complete: %d parsed, %d failures", len(snaps), len(failures))
    return {
        "dims": dims, "snaps": snaps, "failures": failures,
        "seen_tokens": seen_tokens, "snapshot_date": today,
        "sitemap_count": len(entries),
    }


def _upsert_dim(conn, dims: list[tuple]) -> int:
    """Insert dimensions, preserving first_seen / first_list_price on conflict.

    The generic upsert() would overwrite them, which would destroy the
    baseline that price-cut depth is measured against.
    """
    if not dims:
        return 0
    cols = ", ".join(DIM_COLUMNS)
    placeholders = ", ".join(["%s"] * len(DIM_COLUMNS))
    updatable = [
        c for c in DIM_COLUMNS
        if c not in ("address_token", "first_seen", "first_list_price")
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in updatable)
    stmt = (
        f"INSERT INTO listing_dim ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT (address_token) DO UPDATE SET {set_clause}, "
        # only fill first_list_price if we never captured one
        "first_list_price = COALESCE(listing_dim.first_list_price, EXCLUDED.first_list_price), "
        "first_seen = LEAST(listing_dim.first_seen, EXCLUDED.first_seen), "
        "updated_at = now()"
    )
    with conn.cursor() as cur:
        cur.executemany(stmt, dims)
    return len(dims)


def _record_disappearances(conn, seen_tokens: list[str], today: date) -> int:
    """A listing that left the sitemap is a candidate sale/delist, not a delete."""
    if not seen_tokens:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO listing_resolution_events
                (address_token, event_date, event_type, prior_state,
                 last_list_price, days_on_market_at_event)
            SELECT d.address_token, %s, 'DISAPPEARED', s.listing_state,
                   s.list_price, s.days_on_market
            FROM   listing_dim d
            JOIN   LATERAL (
                       SELECT listing_state, list_price, days_on_market
                       FROM   listing_snapshots
                       WHERE  address_token = d.address_token
                       ORDER  BY snapshot_date DESC
                       LIMIT  1
                   ) s ON TRUE
            WHERE  d.last_seen < %s
              AND  NOT EXISTS (
                       SELECT 1 FROM listing_resolution_events e
                       WHERE  e.address_token = d.address_token
                         AND  e.event_type = 'DISAPPEARED'
                         AND  e.event_date >= d.last_seen
                   )
            ON CONFLICT DO NOTHING
            """,
            (today, today),
        )
        return cur.rowcount


def ingest(limit: int | None = None) -> int:
    result = sweep(limit=limit)

    with connect() as conn:
        with ingest_run(conn, "opendoor_listings") as state:
            _upsert_dim(conn, result["dims"])
            written = upsert(
                conn,
                "listing_snapshots",
                SNAP_COLUMNS,
                result["snaps"],
                conflict_keys=["snapshot_date", "address_token"],
            )
            # only look for disappearances on a full sweep
            gone = 0
            if limit is None:
                gone = _record_disappearances(
                    conn, result["seen_tokens"], result["snapshot_date"]
                )

            for url, reason in result["failures"][:500]:
                record_exception(
                    conn, "opendoor_listings", context=url, reason=reason
                )

            state["rows"] = written
            state["detail"] = (
                f"{result['sitemap_count']} in sitemap, {written} snapshots, "
                f"{gone} disappearances, {len(result['failures'])} failures"
            )

    log.info("listing_snapshots: %d rows upserted", written)
    return written


def preview(n: int = 3) -> list[dict[str, Any]]:
    """Scrape a few listings and return the parsed fields (no DB)."""
    entries = fetch_sitemap()[:n]
    out = []
    with opendoor_client() as client:
        for e in entries:
            resp = client.get(e["url"])
            prop = extract_property(resp.text)
            out.append(
                {
                    "token": e["address_token"],
                    "street": prop.get("street"),
                    "city": prop.get("city"),
                    "state": prop.get("state"),
                    "listPrice": prop.get("listPrice"),
                    "buyDirectPrice": prop.get("buyDirectPrice"),
                    "daysOnMarket": prop.get("daysOnMarket"),
                    "listingState": prop.get("listingState"),
                    "pricePerSqFt": prop.get("pricePerSqFt"),
                }
            )
    return out
