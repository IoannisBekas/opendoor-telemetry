"""Workstream 1.2 -- Redfin Data Center public bulk TSV feeds.

Replaces paid MLS / CoreLogic feeds. The files are public, gzipped,
tab-separated, and served straight from S3 with no key.

VERIFIED ENDPOINTS AND SIZES (HEAD requests, 2026-09-20)
-------------------------------------------------------
    redfin_market_tracker/redfin_metro_market_tracker.tsv000.gz   111 MB
    redfin_market_tracker/county_market_tracker.tsv000.gz         241 MB
    redfin_market_tracker/city_market_tracker.tsv000.gz          1.00 GB
    redfin_market_tracker/zip_code_market_tracker.tsv000.gz      1.55 GB
    redfin_market_tracker/state_market_tracker.tsv000.gz          8.6 MB
    redfin_covid19/weekly_housing_market_data_most_recent.tsv000.gz  830 MB

Two gotchas this module exists to handle:

1.  The weekly file is NOT under redfin_market_tracker/ -- that path returns
    HTTP 403. It lives under redfin_covid19/ (a legacy path from when the
    weekly tracker launched in 2020).

2.  The two feeds have DIFFERENT schemas: the metro tracker is 58 columns
    keyed REGION/TABLE_ID, the weekly file is 40 columns keyed
    REGION_NAME/REGION_ID. They get separate parsers and separate tables.

INGESTION STRATEGY
------------------
Decompressing 830 MB of gzip yields multiple GB of TSV, and we want ~6
metros out of 900+. So we never materialise the full file:

    stream gz  ->  incremental decompress  ->  cheap bytes prefilter
               ->  small filtered buffer   ->  polars exact parse/filter

The prefilter is a substring test on the raw line, which is fast and
deliberately over-inclusive; polars then applies the exact region match.
"""

from __future__ import annotations

import gzip
import logging
import re
from pathlib import Path
from typing import Iterator

import polars as pl

from ..config import get_settings
from ..db import connect, ingest_run, upsert
from ..http import generic_client

log = logging.getLogger(__name__)

S3_BASE = "https://redfin-public-data.s3-us-west-2.amazonaws.com"

DATASETS = {
    "metro":   f"{S3_BASE}/redfin_market_tracker/redfin_metro_market_tracker.tsv000.gz",
    "county":  f"{S3_BASE}/redfin_market_tracker/county_market_tracker.tsv000.gz",
    "city":    f"{S3_BASE}/redfin_market_tracker/city_market_tracker.tsv000.gz",
    "zip":     f"{S3_BASE}/redfin_market_tracker/zip_code_market_tracker.tsv000.gz",
    "state":   f"{S3_BASE}/redfin_market_tracker/state_market_tracker.tsv000.gz",
    # NOTE the redfin_covid19/ prefix -- redfin_market_tracker/ 403s here.
    "weekly":  f"{S3_BASE}/redfin_covid19/weekly_housing_market_data_most_recent.tsv000.gz",
}

# upstream TSV column -> our schema column
METRO_MAP = {
    "PERIOD_BEGIN": "period_begin", "PERIOD_END": "period_end",
    "PERIOD_DURATION": "period_duration", "REGION": "region",
    "TABLE_ID": "table_id", "STATE_CODE": "state_code",
    "PROPERTY_TYPE": "property_type", "PROPERTY_TYPE_ID": "property_type_id",
    "IS_SEASONALLY_ADJUSTED": "is_seasonally_adjusted",
    "MEDIAN_SALE_PRICE": "median_sale_price",
    "MEDIAN_SALE_PRICE_YOY": "median_sale_price_yoy",
    "MEDIAN_LIST_PRICE": "median_list_price",
    "MEDIAN_LIST_PRICE_YOY": "median_list_price_yoy",
    "MEDIAN_PPSF": "median_ppsf", "MEDIAN_LIST_PPSF": "median_list_ppsf",
    "HOMES_SOLD": "homes_sold", "HOMES_SOLD_YOY": "homes_sold_yoy",
    "PENDING_SALES": "pending_sales", "NEW_LISTINGS": "new_listings",
    "INVENTORY": "inventory", "INVENTORY_YOY": "inventory_yoy",
    "MONTHS_OF_SUPPLY": "months_of_supply",
    "MEDIAN_DOM": "median_dom", "MEDIAN_DOM_YOY": "median_dom_yoy",
    "AVG_SALE_TO_LIST": "avg_sale_to_list", "SOLD_ABOVE_LIST": "sold_above_list",
    "PRICE_DROPS": "price_drops",
    "OFF_MARKET_IN_TWO_WEEKS": "off_market_in_two_weeks",
    "PARENT_METRO_REGION": "parent_metro_region",
    "LAST_UPDATED": "last_updated",
}

WEEKLY_MAP = {
    "PERIOD_BEGIN": "period_begin", "PERIOD_END": "period_end",
    "REGION_TYPE": "region_type", "REGION_NAME": "region_name",
    "REGION_ID": "region_id", "DURATION": "duration",
    "ADJUSTED_AVERAGE_NEW_LISTINGS": "adjusted_average_new_listings",
    "AVERAGE_PENDING_SALES_LISTING_UPDATES": "average_pending_sales_listing_updates",
    "OFF_MARKET_IN_TWO_WEEKS": "off_market_in_two_weeks",
    "ADJUSTED_AVERAGE_HOMES_SOLD": "adjusted_average_homes_sold",
    "MEDIAN_NEW_LISTING_PRICE": "median_new_listing_price",
    "MEDIAN_SALE_PRICE": "median_sale_price",
    "MEDIAN_DAYS_TO_CLOSE": "median_days_to_close",
    "MEDIAN_NEW_LISTING_PPSF": "median_new_listing_ppsf",
    "ACTIVE_LISTINGS": "active_listings",
    "ACTIVE_LISTINGS_YOY": "active_listings_yoy",
    "MEDIAN_DAYS_ON_MARKET": "median_days_on_market",
    "MEDIAN_DAYS_ON_MARKET_YOY": "median_days_on_market_yoy",
    "PERCENT_ACTIVE_LISTINGS_WITH_PRICE_DROPS": "pct_active_with_price_drops",
    "PERCENT_ACTIVE_LISTINGS_WITH_PRICE_DROPS_YOY": "pct_active_with_price_drops_yoy",
    "AGE_OF_INVENTORY": "age_of_inventory",
    "WEEKS_OF_SUPPLY": "weeks_of_supply",
    "AVERAGE_SALE_TO_LIST_RATIO": "average_sale_to_list_ratio",
    "MEDIAN_SALE_PPSF": "median_sale_ppsf",
    "LAST_UPDATED": "last_updated",
}

NULL_TOKENS = ["NA", "", "NULL", "null"]


# --------------------------------------------------------------------- #
# download with conditional GET
# --------------------------------------------------------------------- #
def download(dataset: str, *, force: bool = False) -> Path:
    """Fetch a bulk file to cache, skipping when Last-Modified is unchanged."""
    if dataset not in DATASETS:
        raise KeyError(f"unknown dataset {dataset!r}; choose from {sorted(DATASETS)}")

    url = DATASETS[dataset]
    settings = get_settings()
    dest = settings.cache_dir / "redfin" / f"{dataset}.tsv000.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)

    with generic_client() as client:
        head = client.head(url)
        remote_lm = head.headers.get("last-modified")
        remote_len = head.headers.get("content-length")

        stamp = dest.with_suffix(".stamp")
        if not force and dest.exists() and stamp.exists():
            if stamp.read_text().strip() == f"{remote_lm}|{remote_len}":
                log.info("%s unchanged upstream (%s bytes); using cache", dataset, remote_len)
                return dest

        log.info("downloading %s (%s bytes) ...", dataset, remote_len)
        tmp = dest.with_suffix(".part")
        written = 0
        with client.stream(url) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)
                    written += len(chunk)
        tmp.replace(dest)
        stamp.write_text(f"{remote_lm}|{remote_len}")
        log.info("%s: %.1f MB written", dataset, written / 1e6)

    return dest


# --------------------------------------------------------------------- #
# streaming prefilter
# --------------------------------------------------------------------- #
def _prefilter_lines(path: Path, needles: list[bytes]) -> Iterator[bytes]:
    """Yield the header plus every line containing one of `needles`.

    Deliberately over-inclusive (a raw substring test); polars applies the
    exact region equality afterwards. This is what keeps a multi-GB
    decompressed stream from ever hitting memory or disk.
    """
    with gzip.open(path, "rb") as fh:
        header = fh.readline()
        yield header
        if not needles:
            for line in fh:
                yield line
            return
        for line in fh:
            if any(n in line for n in needles):
                yield line


def _filtered_buffer(path: Path, needles: list[bytes]) -> bytes:
    return b"".join(_prefilter_lines(path, needles))


def _to_float(colnames: list[str], df: pl.DataFrame, targets: set[str]) -> pl.DataFrame:
    casts = [
        pl.col(c).cast(pl.Float64, strict=False).alias(c)
        for c in colnames
        if c in targets and c in df.columns
    ]
    return df.with_columns(casts) if casts else df


# --------------------------------------------------------------------- #
# parsers
# --------------------------------------------------------------------- #
def parse_metro(path: Path, regions: set[str]) -> pl.DataFrame:
    needles = [r.encode() for r in regions]
    buf = _filtered_buffer(path, needles)

    df = pl.read_csv(
        buf,
        separator="\t",
        quote_char='"',
        null_values=NULL_TOKENS,
        infer_schema_length=0,      # read everything as str, cast explicitly
        truncate_ragged_lines=True,
    )
    keep = [c for c in METRO_MAP if c in df.columns]
    df = df.select(keep).rename({k: METRO_MAP[k] for k in keep})

    # exact region match (the prefilter was intentionally loose)
    df = df.filter(pl.col("region").is_in(list(regions)))

    numeric = {
        "period_duration", "table_id", "property_type_id", "median_sale_price",
        "median_sale_price_yoy", "median_list_price", "median_list_price_yoy",
        "median_ppsf", "median_list_ppsf", "homes_sold", "homes_sold_yoy",
        "pending_sales", "new_listings", "inventory", "inventory_yoy",
        "months_of_supply", "median_dom", "median_dom_yoy", "avg_sale_to_list",
        "sold_above_list", "price_drops", "off_market_in_two_weeks",
    }
    df = _to_float(df.columns, df, numeric)

    return df.with_columns(
        pl.col("period_begin").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("period_end").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("is_seasonally_adjusted")
          .str.to_lowercase().is_in(["true", "t", "1"]).alias("is_seasonally_adjusted"),
        pl.col("table_id").cast(pl.Int64, strict=False),
        pl.col("property_type_id").cast(pl.Int64, strict=False),
        pl.col("period_duration").cast(pl.Int64, strict=False),
    ).drop_nulls(
        subset=["period_begin", "region", "property_type", "table_id", "is_seasonally_adjusted"]
    )


def parse_weekly(path: Path, regions: set[str]) -> pl.DataFrame:
    needles = [r.encode() for r in regions]
    buf = _filtered_buffer(path, needles)

    df = pl.read_csv(
        buf,
        separator="\t",
        quote_char='"',
        null_values=NULL_TOKENS,
        infer_schema_length=0,
        truncate_ragged_lines=True,
    )
    keep = [c for c in WEEKLY_MAP if c in df.columns]
    df = df.select(keep).rename({k: WEEKLY_MAP[k] for k in keep})
    df = df.filter(pl.col("region_name").is_in(list(regions)))

    numeric = set(WEEKLY_MAP.values()) - {
        "period_begin", "period_end", "region_type", "region_name",
        "region_id", "duration", "last_updated",
    }
    df = _to_float(df.columns, df, numeric)

    return df.with_columns(
        pl.col("period_begin").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("period_end").str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        pl.col("region_id").cast(pl.Int64, strict=False),
    ).drop_nulls(subset=["period_begin", "region_id", "duration"])


# --------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------- #
def ingest(dataset: str = "metro", *, force: bool = False) -> int:
    settings = get_settings()
    regions = settings.redfin_metro_names
    if not regions:
        raise RuntimeError("no target regions configured in config/markets.yml")

    path = download(dataset, force=force)

    if dataset == "weekly":
        df = parse_weekly(path, regions)
        table, keys = "redfin_weekly_metrics", ["period_begin", "region_id", "duration"]
    elif dataset == "metro":
        df = parse_metro(path, regions)
        # is_seasonally_adjusted belongs in the key: Redfin ships an adjusted
        # and a raw row per period/region/property type.
        table, keys = "redfin_metro_metrics", [
            "period_begin", "region", "property_type", "table_id", "is_seasonally_adjusted",
        ]
    else:
        raise NotImplementedError(
            f"{dataset!r} downloads fine but has no loader yet; "
            "metro and weekly are the two wired into the schema"
        )

    log.info("%s: %d rows after filtering to %d regions", dataset, df.height, len(regions))
    if df.is_empty():
        log.warning("no rows matched; check region names in config/markets.yml")
        return 0

    # drop the free-text timestamp column; it is metadata, not a metric
    if "last_updated" in df.columns:
        df = df.drop("last_updated")

    columns = df.columns
    rows = df.rows()

    with connect() as conn:
        with ingest_run(conn, f"redfin_{dataset}") as state:
            written = upsert(conn, table, columns, rows, conflict_keys=keys)
            state["rows"] = written
            state["detail"] = f"{len(regions)} regions, {df.height} rows"

    log.info("%s: %d rows upserted into %s", dataset, written, table)
    return written


def summarize(dataset: str = "metro") -> pl.DataFrame:
    """Parse and summarise without writing to the database."""
    settings = get_settings()
    regions = settings.redfin_metro_names
    path = download(dataset)
    df = parse_weekly(path, regions) if dataset == "weekly" else parse_metro(path, regions)
    region_col = "region_name" if dataset == "weekly" else "region"
    return (
        df.group_by(region_col)
        .agg(
            pl.len().alias("rows"),
            pl.col("period_begin").min().alias("from"),
            pl.col("period_begin").max().alias("to"),
        )
        .sort(region_col)
    )
