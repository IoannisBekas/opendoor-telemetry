"""Export the analytical views to a single JSON payload for the dashboard."""
import sys, os, json, datetime, decimal
sys.path.insert(0, "src")
from opendoor_telemetry.db import connect

def jd(o):
    if isinstance(o, decimal.Decimal): return float(o)
    if isinstance(o, (datetime.date, datetime.datetime)): return o.isoformat()
    raise TypeError(str(type(o)))

def rows(cur, sql, params=None):
    cur.execute(sql, params or ())
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

out = {}
with connect() as c, c.cursor() as cur:
    out["as_of"] = datetime.date.today().isoformat()

    # ---- balance sheet, most recent + history
    out["balance_sheet"] = rows(cur, """
        SELECT bs.period_end, bs.abs_debt_current, bs.abs_debt_noncurrent,
               bs.cash_unrestricted, bs.cash_restricted, bs.inventory_real_estate,
               bs.inventory_writedown, bs.convertible_current, bs.convertible_noncurrent,
               bs.stockholders_equity, cs.tangible_net_worth, cs.abs_debt_total,
               cs.debt_to_inventory, cs.liquid_cover_of_current_converts
        FROM v_balance_sheet bs JOIN v_capital_structure cs ON cs.period_end = bs.period_end
        WHERE bs.inventory_real_estate IS NOT NULL
        ORDER BY bs.period_end""")

    # ---- facility detail, latest period
    cur.execute("SELECT max(period_end) FROM v_facility_headroom")
    latest_fac = cur.fetchone()[0]
    out["facility_period"] = latest_fac.isoformat()
    out["facilities"] = rows(cur, """
        SELECT facility_name, facility_group, capacity, drawn, headroom,
               utilization, wtd_avg_rate
        FROM v_facility_headroom WHERE period_end = %s
        ORDER BY capacity DESC NULLS LAST""", (latest_fac,))

    # ---- borrowing base history (TOTAL row per quarter)
    out["facility_history"] = rows(cur, """
        SELECT period_end, capacity, drawn, headroom, utilization
        FROM v_facility_headroom WHERE facility_name = 'TOTAL'
        ORDER BY period_end""")

    # ---- MSA clearance, latest common period
    cur.execute("SELECT max(period_begin) FROM v_msa_vs_national")
    latest_msa = cur.fetchone()[0]
    out["msa_period"] = latest_msa.isoformat()
    out["msa"] = rows(cur, """
        SELECT region, months_of_supply, mos_national, delta_mos, median_dom,
               delta_dom, price_drops, avg_sale_to_list, inventory, homes_sold,
               pending_to_active
        FROM v_msa_vs_national WHERE period_begin = %s
        ORDER BY months_of_supply DESC""", (latest_msa,))

    # ---- MOS time series per metro (last 36 months)
    out["msa_series"] = rows(cur, """
        SELECT period_begin, region, months_of_supply, median_dom, price_drops
        FROM v_msa_vs_national
        WHERE period_begin >= (SELECT max(period_begin) FROM v_msa_vs_national) - interval '36 months'
        ORDER BY period_begin, region""")

    # ---- listings: aging, cuts, per-MSA
    cur.execute("SELECT count(*) FROM listing_snapshots")
    out["listing_count"] = cur.fetchone()[0]
    if out["listing_count"]:
        out["aging"] = rows(cur, """
            SELECT age_bucket, sum(listings) AS listings,
                   sum(carrying_list_value) AS value
            FROM v_inventory_aging GROUP BY age_bucket ORDER BY age_bucket""")
        out["aging_by_msa"] = rows(cur, """
            SELECT msa_key, age_bucket, sum(listings) AS listings
            FROM v_inventory_aging WHERE msa_key IS NOT NULL
            GROUP BY msa_key, age_bucket ORDER BY msa_key, age_bucket""")
        out["dom_dist"] = rows(cur, """
            SELECT width_bucket(days_on_market, 0, 300, 30) AS b,
                   count(*) AS n, min(days_on_market) AS lo, max(days_on_market) AS hi
            FROM v_listing_current WHERE days_on_market IS NOT NULL
            GROUP BY b ORDER BY b""")
        out["km"] = rows(cur, """
            SELECT duration_days, count(*) AS n,
                   count(*) FILTER (WHERE event_observed) AS events
            FROM v_km_input GROUP BY duration_days ORDER BY duration_days""")
        out["listing_msa"] = rows(cur, """
            SELECT COALESCE(msa_key,'other') AS msa_key, count(*) AS listings,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY days_on_market) AS median_dom,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY list_price) AS median_price,
                   avg(price_per_sqft) AS avg_ppsf,
                   sum(list_price) AS total_value
            FROM v_listing_current GROUP BY 1 ORDER BY listings DESC""")
        out["price_position"] = rows(cur, """
            SELECT COALESCE(msa_key,'other') AS msa_key, list_price, days_on_market,
                   price_per_sqft, sqft_living
            FROM v_listing_current
            WHERE list_price IS NOT NULL AND days_on_market IS NOT NULL""")

    cur.execute("SELECT count(*) FROM parse_exceptions")
    out["parse_exceptions"] = cur.fetchone()[0]
    cur.execute("SELECT source, status, rows_written FROM ingest_runs ORDER BY id")
    out["runs"] = [{"source": s, "status": st, "rows": r} for s, st, r in cur.fetchall()]

path = sys.argv[1] if len(sys.argv) > 1 else "dashboard_data.json"
with open(path, "w", encoding="utf-8") as fh:
    json.dump(out, fh, default=jd, indent=1)
print(f"wrote {path}")
for k, v in out.items():
    if isinstance(v, list):
        print(f"  {k:20} {len(v)} rows")
    elif not isinstance(v, (dict,)):
        print(f"  {k:20} {v}")
