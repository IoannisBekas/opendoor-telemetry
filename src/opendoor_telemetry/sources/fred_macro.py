"""Workstream 1.3 -- Macro and mortgage feeds from the St. Louis Fed (FRED).

Zero cost: FRED requires a free API key (no paid tier, no rate card).
Register at https://fredaccount.stlouisfed.org/apikeys and put it in .env.

Series pulled are declared in config/markets.yml so the roster is editable
without touching code. Derived spreads (e.g. the primary-secondary mortgage
spread, MORTGAGE30US - DGS10) are computed here and written back into
macro_ts_metrics under their own metric_key, so downstream SQL treats them
exactly like a native series.

Ingestion is incremental: we ask FRED only for observations after the newest
date already stored for that series.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from ..config import get_settings
from ..db import connect, ingest_run, upsert

log = logging.getLogger(__name__)

# Regional house price indices (FHFA all-transactions, via FRED) per market.
# Keyed by the market `key` in config/markets.yml.
REGIONAL_HPI = {
    "phoenix":   "ATNHPIUS38060Q",
    "atlanta":   "ATNHPIUS12060Q",
    "dfw":       "ATNHPIUS19100Q",
    "charlotte": "ATNHPIUS16740Q",
    "tampa":     "ATNHPIUS45300Q",
    "las_vegas": "ATNHPIUS29820Q",
}


def _fred_client():
    settings = get_settings()
    if not settings.fred_api_key:
        raise RuntimeError(
            "FRED_API_KEY is not set. Get a free key at "
            "https://fredaccount.stlouisfed.org/apikeys and add it to .env"
        )
    from fredapi import Fred  # imported lazily so the package stays optional

    return Fred(api_key=settings.fred_api_key)


def _latest_dates(conn, keys: list[str]) -> dict[str, date]:
    if not keys:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT metric_key, MAX(date) FROM macro_ts_metrics "
            "WHERE metric_key = ANY(%s) GROUP BY metric_key",
            (keys,),
        )
        return {k: d for k, d in cur.fetchall() if d is not None}


def fetch_series(fred, series_id: str, start: date | None) -> pd.Series:
    kwargs = {}
    if start is not None:
        # re-fetch the last stored point so revisions land
        kwargs["observation_start"] = (start - timedelta(days=7)).isoformat()
    s = fred.get_series(series_id, **kwargs)
    return s.dropna()


def ingest(include_regional: bool = True) -> int:
    settings = get_settings()
    fred = _fred_client()

    series_ids = list(settings.fred_series.keys())
    if include_regional:
        series_ids += [sid for sid in REGIONAL_HPI.values()]

    rows: list[tuple] = []

    with connect() as conn:
        latest = _latest_dates(conn, series_ids)

        for sid in series_ids:
            start = latest.get(sid)
            try:
                s = fetch_series(fred, sid, start)
            except Exception as exc:  # a dead series must not kill the run
                log.warning("FRED series %s failed: %s", sid, exc)
                continue
            for idx, val in s.items():
                rows.append((idx.date(), sid, float(val)))
            log.info("%-16s %5d observations (from %s)", sid, len(s), start or "beginning")

        # ---- derived spreads -------------------------------------------
        frame = pd.DataFrame(rows, columns=["date", "metric_key", "value"])
        for name, spec in settings.derived_series.items():
            a, b = spec["minuend"], spec["subtrahend"]
            left = frame[frame.metric_key == a].set_index("date")["value"]
            right = frame[frame.metric_key == b].set_index("date")["value"]
            if left.empty or right.empty:
                log.warning("cannot derive %s: %s or %s missing from this pull", name, a, b)
                continue
            # weekly vs daily cadence: forward-fill the slower leg onto the faster
            joined = pd.concat([left, right], axis=1, keys=["a", "b"]).sort_index().ffill()
            spread = (joined["a"] - joined["b"]).dropna()
            for idx, val in spread.items():
                rows.append((idx, name, float(val)))
            log.info("%-16s %5d observations (derived)", name, len(spread))

        with ingest_run(conn, "fred_macro") as state:
            written = upsert(
                conn,
                "macro_ts_metrics",
                ["date", "metric_key", "value"],
                rows,
                conflict_keys=["date", "metric_key"],
            )
            state["rows"] = written
            state["detail"] = f"{len(series_ids)} series + {len(settings.derived_series)} derived"

    log.info("macro_ts_metrics: %d rows upserted", written)
    return written


def preview(series_id: str = "MORTGAGE30US", n: int = 5) -> pd.Series:
    """Fetch a series without writing to the database."""
    return fetch_series(_fred_client(), series_id, None).tail(n)
