"""Workstream 1.1a -- Opendoor financials from the free SEC EDGAR XBRL API.

Endpoint (no key, no rate-limited paid tier):
    https://data.sec.gov/api/xbrl/companyfacts/CIK0001801169.json   (~1.3 MB)

Two properties of companyfacts.json drive the design here, both verified
against the live payload:

1.  It exposes only the `dei`, `us-gaap` and `ecd` taxonomies. Opendoor's
    custom `open_` extension tags are NOT present, and every fact is
    dimensionally COLLAPSED -- there is no per-facility breakdown and no
    borrowing-base capacity at all. That detail lives in the rendered
    footnote tables; see edgar_footnotes.py.

2.  Tag usage drifts across years. `LongTermDebt` / `LongTermDebtCurrent`
    were used through 2021 and then abandoned in favour of
    `LongTermLineOfCredit` / `LinesOfCreditCurrent`. Extracting a single
    hardcoded tag silently yields nulls for half the history, so every
    concept below resolves through an ordered fallback chain.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from ..config import CIK_PADDED
from ..db import connect, ingest_run, upsert
from ..http import sec_client

log = logging.getLogger(__name__)

COMPANYFACTS_URL = f"https://data.sec.gov/api/xbrl/companyfacts/{CIK_PADDED}.json"

# Ordered fallback chains. First tag present for a given period wins.
CONCEPT_CHAINS: dict[str, list[str]] = {
    "abs_debt_current": [
        "LinesOfCreditCurrent",
        "SecuredDebtCurrent",
        "LongTermDebtCurrent",
    ],
    "abs_debt_noncurrent": [
        "LongTermLineOfCredit",
        "LongTermDebt",
    ],
    "unrestricted_cash": [
        "CashAndCashEquivalentsAtCarryingValue",
    ],
    "marketable_securities": [
        "MarketableSecuritiesCurrent",
        "MarketableSecurities",
    ],
    "restricted_cash": [
        "RestrictedCash",
        "RestrictedCashAndCashEquivalentsAtCarryingValue",
    ],
    "inventory": [
        "InventoryRealEstate",
    ],
    "inventory_writedown": [
        "InventoryWriteDown",
    ],
    "convertible_current": [
        "ConvertibleDebtCurrent",
    ],
    "convertible_noncurrent": [
        "ConvertibleDebtNoncurrent",
    ],
    "equity": [
        "StockholdersEquity",
    ],
    "goodwill": [
        "Goodwill",
    ],
    "intangibles": [
        "IntangibleAssetsNetExcludingGoodwill",
    ],
    "cash_from_ops": [
        "NetCashProvidedByUsedInOperatingActivities",
    ],
}

# Every tag we persist (union of the chains, order-preserving).
TRACKED_TAGS: list[str] = list(
    dict.fromkeys(tag for chain in CONCEPT_CHAINS.values() for tag in chain)
)

FACT_COLUMNS = [
    "tag", "period_end", "period_start", "accession", "form",
    "frame", "fy", "fp", "unit", "value", "filed",
]


def fetch_companyfacts() -> dict[str, Any]:
    with sec_client() as client:
        log.info("GET %s", COMPANYFACTS_URL)
        return client.get_json(COMPANYFACTS_URL)


def iter_facts(payload: dict[str, Any], tags: list[str] | None = None) -> Iterator[tuple]:
    """Yield one row per (tag, period, accession) for the tracked tags."""
    tags = tags or TRACKED_TAGS
    gaap = payload.get("facts", {}).get("us-gaap", {})

    for tag in tags:
        node = gaap.get(tag)
        if node is None:
            log.debug("tag absent from companyfacts: %s", tag)
            continue

        for unit, entries in node.get("units", {}).items():
            for e in entries:
                # 'end' is always present; 'start' only on duration facts.
                if e.get("end") is None or e.get("val") is None:
                    continue
                yield (
                    tag,
                    e["end"],
                    e.get("start"),
                    e.get("accn", ""),
                    e.get("form", ""),
                    e.get("frame"),
                    e.get("fy"),
                    e.get("fp"),
                    unit,
                    e["val"],
                    e.get("filed"),
                )


def resolve_concept(
    facts_by_tag: dict[str, dict[str, float]], concept: str, period_end: str
) -> tuple[str | None, float | None]:
    """Walk a concept's fallback chain; return (winning_tag, value)."""
    for tag in CONCEPT_CHAINS[concept]:
        val = facts_by_tag.get(tag, {}).get(period_end)
        if val is not None:
            return tag, val
    return None, None


def build_concept_index(rows: list[tuple]) -> dict[str, dict[str, float]]:
    """Collapse raw fact rows to {tag: {period_end: value}} keeping newest filing."""
    index: dict[str, dict[str, float]] = {}
    newest_filed: dict[tuple[str, str], str] = {}

    for tag, end, _start, _accn, _form, _frame, _fy, _fp, unit, val, filed in rows:
        if unit != "USD":
            continue
        key = (tag, end)
        prior = newest_filed.get(key)
        if prior is None or (filed or "") >= prior:
            newest_filed[key] = filed or ""
            index.setdefault(tag, {})[end] = val
    return index


def ingest() -> int:
    """Download companyfacts and upsert tracked tags into sec_facts."""
    payload = fetch_companyfacts()
    entity = payload.get("entityName", "?")
    rows = list(iter_facts(payload))
    log.info("%s: %d facts across %d tracked tags", entity, len(rows), len(TRACKED_TAGS))

    # Drop rows without an accession or filed date; they cannot be keyed.
    rows = [r for r in rows if r[3] and r[10]]

    with connect() as conn:
        with ingest_run(conn, "edgar_facts") as state:
            written = upsert(
                conn,
                "sec_facts",
                FACT_COLUMNS,
                rows,
                conflict_keys=["tag", "period_end", "accession"],
            )
            state["rows"] = written
            state["detail"] = f"{entity}: {len(TRACKED_TAGS)} tags"
    log.info("sec_facts: %d rows upserted", written)
    return written


def latest_snapshot() -> dict[str, Any]:
    """Convenience: resolve every concept for the most recent period.

    Used by the CLI verify command; does not touch the database.
    """
    payload = fetch_companyfacts()
    rows = list(iter_facts(payload))
    index = build_concept_index(rows)

    periods = sorted({end for tag in index.values() for end in tag})
    if not periods:
        return {}
    latest = periods[-1]

    out: dict[str, Any] = {"period_end": latest, "entity": payload.get("entityName")}
    for concept in CONCEPT_CHAINS:
        tag, val = resolve_concept(index, concept, latest)
        out[concept] = {"tag": tag, "value": val}

    eq = out["equity"]["value"]
    gw = out["goodwill"]["value"] or 0
    ia = out["intangibles"]["value"] or 0
    out["tangible_net_worth"] = (eq - gw - ia) if eq is not None else None
    return out
