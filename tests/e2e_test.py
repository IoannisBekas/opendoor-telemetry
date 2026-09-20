"""End-to-end test of the opendoor-telemetry pipeline against a live Postgres."""
import sys, os, time, datetime
sys.path.insert(0, "src")

import psycopg
from opendoor_telemetry.db import connect, apply_schema
from opendoor_telemetry.config import get_settings

RULE = "=" * 78
def hdr(t): print(f"\n{RULE}\n{t}\n{RULE}")

fails = []
def check(label, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{('  -> ' + str(detail)) if detail else ''}")
    if not cond:
        fails.append(label)

# --------------------------------------------------------------- schema
hdr("1. APPLY SCHEMA (sql/001_schema.sql + sql/002_views.sql)")
apply_schema()
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='od' AND table_type='BASE TABLE' ORDER BY 1")
    tables = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT table_name FROM information_schema.views WHERE table_schema='od' ORDER BY 1")
    views = [r[0] for r in cur.fetchall()]
print(f"  tables ({len(tables)}): {', '.join(tables)}")
print(f"  views  ({len(views)}): {', '.join(views)}")
check("10 tables created", len(tables) == 10, len(tables))
check("11 views created", len(views) == 11, len(views))

# --------------------------------------------------------------- SEC
hdr("2. INGEST :: SEC XBRL companyfacts")
from opendoor_telemetry.sources import edgar_facts
n = edgar_facts.ingest()
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT count(*) FROM sec_facts")
    total = cur.fetchone()[0]
    cur.execute("""SELECT bs.abs_debt_current, bs.abs_debt_noncurrent, bs.cash_unrestricted,
                          bs.inventory_real_estate, bs.convertible_current, cs.tangible_net_worth
                   FROM v_capital_structure cs
                   JOIN v_balance_sheet bs ON bs.period_end = cs.period_end
                   WHERE cs.period_end = '2026-06-30'""")
    row = cur.fetchone()
print(f"  rows upserted: {n}, rows in table: {total}")
check("sec_facts populated", total > 500, total)
check("abs_debt_current == 691,000,000", row[0] == 691_000_000, f"{row[0]:,}")
check("abs_debt_noncurrent == 1,071,000,000", row[1] == 1_071_000_000, f"{row[1]:,}")
check("cash_unrestricted == 896,000,000", row[2] == 896_000_000, f"{row[2]:,}")
check("inventory == 1,845,000,000", row[3] == 1_845_000_000, f"{row[3]:,}")
check("convertible_current == 194,000,000", row[4] == 194_000_000, f"{row[4]:,}")
check("tangible_net_worth == 911,000,000", row[5] == 911_000_000, f"{row[5]:,}")

# idempotency
edgar_facts.ingest()
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT count(*) FROM sec_facts")
    total2 = cur.fetchone()[0]
check("SEC ingest is idempotent", total == total2, f"{total} -> {total2}")

# --------------------------------------------------------------- footnotes
hdr("3. INGEST :: EDGAR footnote R-files (borrowing base)")
from opendoor_telemetry.sources import edgar_footnotes
n = edgar_footnotes.ingest(limit=3)
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT count(*) FROM debt_facilities")
    nf = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM parse_exceptions WHERE source='edgar_footnotes'")
    nx = cur.fetchone()[0]
    cur.execute("""SELECT facility_name, capacity, drawn, headroom, utilization, wtd_avg_rate
                   FROM v_facility_headroom WHERE period_end='2026-06-30'
                   ORDER BY capacity DESC NULLS LAST""")
    rows = cur.fetchall()
print(f"  rows upserted: {n}, facilities stored: {nf}, parse exceptions: {nx}")
print(f"\n  {'facility':<44}{'capacity':>16}{'drawn':>16}{'util':>8}{'rate':>8}")
for fn, cap, drawn, hr, util, rate in rows:
    print(f"  {fn[:43]:<44}{(f'{cap:,.0f}' if cap else '-'):>16}"
          f"{(f'{drawn:,.0f}' if drawn else '-'):>16}"
          f"{(f'{util:.1%}' if util is not None else '-'):>8}"
          f"{(f'{rate:.2%}' if rate is not None else '-'):>8}")
tot = [r for r in rows if r[0] == "TOTAL"]
check("facilities loaded", nf >= 12, nf)
check("no parse exceptions", nx == 0, nx)
check("TOTAL capacity == $7.45B", bool(tot) and tot[0][1] == 7_450_000_000, f"{tot[0][1]:,.0f}" if tot else "missing")
check("mezzanine rate captured at 12.50%",
      any(r[5] is not None and abs(float(r[5]) - 0.125) < 1e-9 for r in rows))

# --------------------------------------------------------------- redfin
hdr("4. INGEST :: Redfin metro bulk TSV")
from opendoor_telemetry.sources import redfin_bulk
n = redfin_bulk.ingest("metro")
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT count(*) FROM redfin_metro_metrics")
    nr = cur.fetchone()[0]
    cur.execute("SELECT count(DISTINCT region) FROM redfin_metro_metrics")
    nreg = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM redfin_metro_metrics
                   WHERE is_seasonally_adjusted IS TRUE""")
    nadj = cur.fetchone()[0]
    cur.execute("""SELECT region, months_of_supply, delta_mos, median_dom, price_drops
                   FROM v_msa_vs_national WHERE period_begin='2026-05-01' ORDER BY delta_mos DESC""")
    msa = cur.fetchall()
print(f"  rows upserted: {n}, in table: {nr}, distinct regions: {nreg}, seasonally-adjusted rows: {nadj}")
print(f"\n  {'region':<30}{'MOS':>8}{'vs natl':>10}{'DOM':>8}{'cuts':>8}")
for r, mos, dm, dom, pd_ in msa:
    print(f"  {r[:29]:<30}{(f'{mos:.2f}' if mos else '-'):>8}"
          f"{(f'{dm:+.2f}' if dm is not None else '-'):>10}"
          f"{(f'{dom:.0f}' if dom else '-'):>8}{(f'{pd_:.1%}' if pd_ else '-'):>8}")
check("redfin rows loaded", nr > 10000, nr)
check("all 7 target regions present", nreg == 7, nreg)
check("seasonally-adjusted rows retained (the PK fix)", nadj > 4000, nadj)
check("v_msa_vs_national returns 7 metros", len(msa) == 7, len(msa))

# idempotency
redfin_bulk.ingest("metro")
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT count(*) FROM redfin_metro_metrics")
    nr2 = cur.fetchone()[0]
check("Redfin ingest is idempotent", nr == nr2, f"{nr} -> {nr2}")

# --------------------------------------------------------------- listings
hdr("5. INGEST :: Opendoor listings (sample)")
from opendoor_telemetry.sources import opendoor_listings
n = opendoor_listings.ingest(limit=40)
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT count(*) FROM listing_snapshots")
    ns = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM listing_dim")
    nd = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM listing_dim WHERE msa_key IS NOT NULL")
    nm = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM listing_snapshots WHERE days_on_market IS NOT NULL")
    ndom = cur.fetchone()[0]
    cur.execute("SELECT msa_key, count(*), avg(days_on_market)::numeric(6,1) FROM v_listing_current GROUP BY 1 ORDER BY 2 DESC")
    bym = cur.fetchall()
print(f"  snapshots: {ns}, dimensions: {nd}, with msa_key: {nm}, with DOM: {ndom}")
for k, cnt, dom in bym:
    print(f"    {str(k):<14}{cnt:>4} listings   avg DOM {dom}")
check("snapshots written", ns >= 35, ns)
check("dim rows written", nd == ns, f"{nd} vs {ns}")
check("days_on_market populated", ndom >= 35, ndom)
check("some listings assigned to an MSA", nm > 0, nm)

# re-run same day must not duplicate, and must preserve first_list_price
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT address_token, first_list_price, first_seen FROM listing_dim ORDER BY address_token LIMIT 1")
    before = cur.fetchone()
opendoor_listings.ingest(limit=40)
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT count(*) FROM listing_snapshots")
    ns2 = cur.fetchone()[0]
    cur.execute("SELECT address_token, first_list_price, first_seen FROM listing_dim WHERE address_token=%s", (before[0],))
    after = cur.fetchone()
check("listings ingest is idempotent (same day)", ns == ns2, f"{ns} -> {ns2}")
check("first_list_price preserved on re-ingest", before[1] == after[1], f"{before[1]} -> {after[1]}")
check("first_seen preserved on re-ingest", before[2] == after[2], f"{before[2]} -> {after[2]}")

# --------------------------------------------------------------- views
hdr("6. ANALYTICAL VIEWS :: execute every one")
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT table_name FROM information_schema.views WHERE table_schema='od' ORDER BY 1")
    for (v,) in cur.fetchall():
        try:
            cur.execute(f"SELECT count(*) FROM {v}")
            print(f"  [PASS] {v:<26} {cur.fetchone()[0]:>7} rows")
        except Exception as e:
            print(f"  [FAIL] {v:<26} {str(e)[:90]}")
            fails.append(f"view {v}")
            c.rollback()

hdr("7. INGEST RUN BOOKKEEPING")
with connect() as c, c.cursor() as cur:
    cur.execute("SELECT source, status, rows_written, detail FROM ingest_runs ORDER BY id")
    for s, st, rw, d in cur.fetchall():
        print(f"  {s:<20}{st:<8}{rw:>8} rows   {(d or '')[:60]}")
    cur.execute("SELECT count(*) FROM ingest_runs WHERE status <> 'OK'")
    bad = cur.fetchone()[0]
check("all ingest runs reported OK", bad == 0, bad)

hdr("RESULT")
print(f"  {'ALL CHECKS PASSED' if not fails else f'{len(fails)} FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
