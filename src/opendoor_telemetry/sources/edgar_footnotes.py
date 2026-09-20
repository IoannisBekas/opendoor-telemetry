"""Workstream 1.1b -- Borrowing base capacity from EDGAR footnote R-files.

WHY THIS MODULE EXISTS
----------------------
There is no us-gaap XBRL tag for borrowing base / facility capacity, and
companyfacts.json is dimensionally collapsed, so it cannot express
per-facility detail either. Verified against the live Opendoor payload:
capacity simply is not in there.

It *is* in the rendered footnote tables that EDGAR ships with every filing.
FilingSummary.xml indexes them; for the 2026-Q2 10-Q the relevant report is
"Schedule of Credit Facilities and Long Term Debt (Details)", which carries
total Borrowing Capacity, the senior/mezzanine split, and per-facility rows
with weighted-average interest rates.

The report NUMBER shifts between filings, so we always match on ShortName
and never hardcode R45.htm.

TABLE SHAPE (verified)
----------------------
A flat 3-column frame: [label, period_1_value, period_2_value].
  * The header cell carries the scale, e.g. "... - USD ($)  $ in Millions".
  * Column headers are period dates, e.g. "Jun. 30, 2026".
  * Hierarchy is by convention: a label that is not a known metric and has
    no values opens a new facility block. Labels before the first such row
    belong to the consolidated TOTAL block.
  * "X | Y" splits into facility name X and axis/group Y.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime
from typing import Any, Iterator

import pandas as pd

from ..config import CIK, CIK_PADDED
from ..db import connect, ingest_run, record_exception, upsert
from ..http import sec_client

log = logging.getLogger(__name__)

SUBMISSIONS_URL = f"https://data.sec.gov/submissions/{CIK_PADDED}.json"
ARCHIVE_BASE = f"https://www.sec.gov/Archives/edgar/data/{CIK}"

# Match on ShortName; report numbering is not stable across filings.
FACILITY_REPORT_PATTERN = re.compile(
    r"schedule of credit facilities and long[- ]term debt", re.I
)
FACILITY_REPORT_FALLBACK = re.compile(
    r"(credit facilit|asset-backed|borrowing)", re.I
)

NOISE_LABELS = {
    "debt instrument [line items]",
    "line of credit facility [line items]",
    "debt instrument, redemption [line items]",
}

# label (lowercased, normalised) -> (field, aggregation)
METRIC_LABELS: dict[str, tuple[str, str]] = {
    "borrowing capacity": ("borrowing_capacity", "first"),
    "maximum borrowing capacity": ("borrowing_capacity", "first"),
    "outstanding, current": ("outstanding_current", "first"),
    "outstanding amount, current": ("outstanding_current", "first"),
    "outstanding, noncurrent": ("outstanding_noncurrent", "first"),
    "outstanding amount, noncurrent": ("outstanding_noncurrent", "first"),
    "issuance costs": ("issuance_costs", "sum"),
    "carrying value": ("net_carrying_amount", "last"),
    "net carrying amount": ("net_carrying_amount", "last"),
    "weighted average interest rate (in percent)": ("wtd_avg_rate", "first"),
    "weighted average interest rate": ("wtd_avg_rate", "first"),
}

FACILITY_COLUMNS = [
    "accession", "period_end", "facility_group", "facility_name",
    "borrowing_capacity", "outstanding_current", "outstanding_noncurrent",
    "issuance_costs", "net_carrying_amount", "wtd_avg_rate",
    "scale_factor", "source_report",
]


# --------------------------------------------------------------------- #
# value / header parsing
# --------------------------------------------------------------------- #
def parse_scale(header: str) -> float:
    h = header.lower()
    if "in millions" in h:
        return 1e6
    if "in thousands" in h:
        return 1e3
    if "in billions" in h:
        return 1e9
    return 1.0


def parse_period(col_header: str) -> date | None:
    """'Jun. 30, 2026' -> date(2026, 6, 30). Also tolerates duration headers."""
    text = str(col_header).strip()
    # Duration columns look like '6 Months Ended Jun. 30, 2026'; take the tail.
    m = re.search(r"([A-Z][a-z]{2}\.?\s+\d{1,2},\s+\d{4})", text)
    if not m:
        return None
    token = m.group(1).replace(".", "")
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def parse_value(raw: Any) -> tuple[float | None, bool]:
    """Return (value, is_percent). Handles $, commas, (negatives), %, NaN."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None, False
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "none", "-", "—"}:
        return None, False

    is_pct = "%" in s
    negative = "(" in s and ")" in s
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in {"-", ".", "-."}:
        return None, is_pct
    try:
        val = float(s)
    except ValueError:
        return None, is_pct
    if negative:
        val = -abs(val)
    if is_pct:
        val = val / 100.0
    return val, is_pct


def split_facility(label: str) -> tuple[str, str | None]:
    """'Revolving Facility 2018-2 | Asset-backed Senior ...' -> (name, group)."""
    if "|" in label:
        left, right = label.split("|", 1)
        return left.strip(), right.strip()
    return label.strip(), None


# --------------------------------------------------------------------- #
# filing discovery
# --------------------------------------------------------------------- #
def list_filings(forms: tuple[str, ...] = ("10-Q", "10-K"), limit: int | None = None) -> list[dict]:
    with sec_client() as client:
        payload = client.get_json(SUBMISSIONS_URL)

    recent = payload["filings"]["recent"]
    out: list[dict] = []
    for i, form in enumerate(recent["form"]):
        if form not in forms:
            continue
        out.append(
            {
                "form": form,
                "accession": recent["accessionNumber"][i],
                "accession_nodash": recent["accessionNumber"][i].replace("-", ""),
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
            }
        )
        if limit and len(out) >= limit:
            break
    return out


def find_facility_reports(client, accession_nodash: str) -> list[dict]:
    """Locate the credit-facility R-files via FilingSummary.xml."""
    url = f"{ARCHIVE_BASE}/{accession_nodash}/FilingSummary.xml"
    resp = client.get(url)
    if resp.status_code != 200:
        return []

    try:
        summary = pd.read_xml(io.StringIO(resp.text), xpath=".//Report")
    except (ValueError, SyntaxError) as exc:
        log.warning("FilingSummary parse failed for %s: %s", accession_nodash, exc)
        return []

    if "ShortName" not in summary.columns or "HtmlFileName" not in summary.columns:
        return []

    summary = summary.dropna(subset=["ShortName", "HtmlFileName"])
    primary = summary[summary["ShortName"].str.contains(FACILITY_REPORT_PATTERN, na=False)]
    if primary.empty:
        primary = summary[summary["ShortName"].str.contains(FACILITY_REPORT_FALLBACK, na=False)]

    return primary[["ShortName", "HtmlFileName"]].to_dict("records")


# --------------------------------------------------------------------- #
# table -> rows
# --------------------------------------------------------------------- #
def parse_facility_table(
    df: pd.DataFrame, *, all_periods: bool = False
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Convert one rendered R-file table into facility records.

    Returns (records, unmatched) where unmatched rows are logged to
    parse_exceptions so layout drift stays visible instead of silently
    dropping a facility.
    """
    if df.shape[1] < 2:
        return [], []

    header = str(df.columns[0])
    scale = parse_scale(header)

    # Value columns, in document order; column 0 is the label.
    value_cols = list(df.columns[1:])
    periods = [(c, parse_period(str(c))) for c in value_cols]
    periods = [(c, p) for c, p in periods if p is not None]
    if not periods:
        return [], []
    if not all_periods:
        periods = periods[:1]  # the filing's own reporting date

    unmatched: list[tuple[str, str]] = []
    # blocks[(period, facility_name)] = record
    blocks: dict[tuple[date, str], dict[str, Any]] = {}
    current_name, current_group = "TOTAL", None

    for _, row in df.iterrows():
        label_raw = str(row.iloc[0]).strip()
        if not label_raw or label_raw.lower() == "nan":
            continue
        key = re.sub(r"\s+", " ", label_raw).strip().lower()

        if key in NOISE_LABELS:
            continue

        metric = METRIC_LABELS.get(key)
        if metric is None:
            # Not a known metric -> treat as a block header for a facility.
            current_name, current_group = split_facility(label_raw)
            if len(current_name) > 200:
                unmatched.append((label_raw[:200], "label too long for facility name"))
                current_name, current_group = "TOTAL", None
            continue

        field, agg = metric
        for col, period in periods:
            val, is_pct = parse_value(row[col])
            if val is None:
                continue
            rec = blocks.setdefault(
                (period, current_name),
                {
                    "facility_name": current_name,
                    "facility_group": current_group,
                    "period_end": period,
                    "scale_factor": 1.0 if field == "wtd_avg_rate" else scale,
                },
            )
            # rates are unitless; never scale them
            if field == "wtd_avg_rate":
                rec[field] = val
                continue

            if agg == "sum":
                rec[field] = (rec.get(field) or 0) + val
            elif agg == "last" or field not in rec:
                rec[field] = val

    return list(blocks.values()), unmatched


def ingest(limit: int | None = 8, all_periods: bool = False) -> int:
    """Walk recent 10-Q/10-K filings and load their facility tables."""
    filings = list_filings(limit=limit)
    log.info("scanning %d filings for credit-facility footnotes", len(filings))

    all_rows: list[tuple] = []
    problems: list[tuple[str, str, str]] = []

    with sec_client() as client:
        for f in filings:
            reports = find_facility_reports(client, f["accession_nodash"])
            if not reports:
                problems.append((f["accession"], "", "no credit-facility report in FilingSummary"))
                log.warning("%s %s: no facility report found", f["form"], f["accession"])
                continue

            report = reports[0]  # the schedule table; narratives follow it
            url = f"{ARCHIVE_BASE}/{f['accession_nodash']}/{report['HtmlFileName']}"
            resp = client.get(url)
            if resp.status_code != 200:
                problems.append((f["accession"], report["HtmlFileName"], f"HTTP {resp.status_code}"))
                continue

            try:
                tables = pd.read_html(io.StringIO(resp.text))
            except ValueError as exc:
                problems.append((f["accession"], report["HtmlFileName"], f"read_html: {exc}"))
                continue

            if not tables:
                continue

            records, unmatched = parse_facility_table(tables[0], all_periods=all_periods)
            for lbl, reason in unmatched:
                problems.append((f["accession"], lbl, reason))

            # A report that matched but yielded nothing is a silent miss --
            # usually the fallback pattern caught the narrative note rather
            # than the schedule table. Surface it instead of logging zero.
            if not records:
                problems.append(
                    (
                        f["accession"],
                        report["ShortName"],
                        f"matched {report['HtmlFileName']} but parsed 0 facility rows",
                    )
                )

            for r in records:
                all_rows.append(
                    (
                        f["accession"],
                        r["period_end"],
                        r.get("facility_group"),
                        r["facility_name"],
                        r.get("borrowing_capacity"),
                        r.get("outstanding_current"),
                        r.get("outstanding_noncurrent"),
                        r.get("issuance_costs"),
                        r.get("net_carrying_amount"),
                        r.get("wtd_avg_rate"),
                        r["scale_factor"],
                        report["HtmlFileName"],
                    )
                )
            log.info(
                "%s %s -> %s: %d facility rows",
                f["form"], f["report_date"], report["HtmlFileName"], len(records),
            )

    with connect() as conn:
        with ingest_run(conn, "edgar_footnotes") as state:
            written = upsert(
                conn,
                "debt_facilities",
                FACILITY_COLUMNS,
                all_rows,
                conflict_keys=["accession", "period_end", "facility_name"],
            )
            for accn, label, reason in problems:
                record_exception(
                    conn, "edgar_footnotes", accession=accn,
                    raw_label=label or None, reason=reason,
                )
            state["rows"] = written
            state["detail"] = f"{len(filings)} filings, {len(problems)} exceptions"

    log.info("debt_facilities: %d rows upserted (%d exceptions)", written, len(problems))
    return written


def preview(accession_nodash: str | None = None) -> pd.DataFrame:
    """Parse the newest facility table without touching the database."""
    if accession_nodash is None:
        accession_nodash = list_filings(limit=1)[0]["accession_nodash"]
    with sec_client() as client:
        reports = find_facility_reports(client, accession_nodash)
        if not reports:
            raise RuntimeError(f"no facility report for {accession_nodash}")
        url = f"{ARCHIVE_BASE}/{accession_nodash}/{reports[0]['HtmlFileName']}"
        tables = pd.read_html(io.StringIO(client.get(url).text))
    records, _ = parse_facility_table(tables[0])
    return pd.DataFrame(records)
