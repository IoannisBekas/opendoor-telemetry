-- =====================================================================
-- Opendoor Telemetry :: analytical views
-- Implements the formulas from the institutional framework doc.
-- Safe to re-run.
-- =====================================================================

SET search_path = od, public;

-- ---------------------------------------------------------------------
-- v_sec_latest :: restatement-aware fact view
-- companyfacts repeats a period across filings; keep the newest `filed`.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_sec_latest AS
SELECT DISTINCT ON (tag, period_end)
       tag, period_end, frame, form, accession, unit, value, filed
FROM   sec_facts
ORDER BY tag, period_end, filed DESC;

-- ---------------------------------------------------------------------
-- v_balance_sheet :: one row per period with the framework line items
-- Fallback chains mirror edgar_facts.py because tag usage drifted:
-- LongTermDebt / LongTermDebtCurrent stop after 2021.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_balance_sheet AS
WITH p AS (SELECT DISTINCT period_end FROM v_sec_latest),
     f AS (SELECT tag, period_end, value FROM v_sec_latest)
SELECT
    p.period_end,
    COALESCE(
        (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'LinesOfCreditCurrent'),
        (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'SecuredDebtCurrent'),
        (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'LongTermDebtCurrent')
    )                                                                   AS abs_debt_current,
    COALESCE(
        (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'LongTermLineOfCredit'),
        (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'LongTermDebt')
    )                                                                   AS abs_debt_noncurrent,
    (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'CashAndCashEquivalentsAtCarryingValue')
                                                                        AS cash_unrestricted,
    COALESCE((SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'MarketableSecuritiesCurrent'), 0)
                                                                        AS marketable_securities,
    COALESCE(
        (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'RestrictedCash'),
        (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'RestrictedCashAndCashEquivalentsAtCarryingValue')
    )                                                                   AS cash_restricted,
    (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'InventoryRealEstate')
                                                                        AS inventory_real_estate,
    (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'InventoryWriteDown')
                                                                        AS inventory_writedown,
    COALESCE((SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'ConvertibleDebtCurrent'), 0)
                                                                        AS convertible_current,
    COALESCE((SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'ConvertibleDebtNoncurrent'), 0)
                                                                        AS convertible_noncurrent,
    (SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'StockholdersEquity')
                                                                        AS stockholders_equity,
    COALESCE((SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'Goodwill'), 0)
                                                                        AS goodwill,
    COALESCE((SELECT value FROM f WHERE f.period_end = p.period_end AND tag = 'IntangibleAssetsNetExcludingGoodwill'), 0)
                                                                        AS intangibles
FROM p;

-- ---------------------------------------------------------------------
-- v_capital_structure :: leverage, TNW covenant, liquidity
--   TNW = Total Stockholders Equity - Intangibles - Goodwill
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_capital_structure AS
SELECT
    period_end,
    COALESCE(abs_debt_current, 0) + COALESCE(abs_debt_noncurrent, 0)    AS abs_debt_total,
    convertible_current + convertible_noncurrent                        AS convertible_total,
    cash_unrestricted + marketable_securities                           AS liquid_assets,
    inventory_real_estate,
    stockholders_equity - goodwill - intangibles                        AS tangible_net_worth,
    CASE WHEN NULLIF(inventory_real_estate, 0) IS NOT NULL
         THEN (COALESCE(abs_debt_current, 0) + COALESCE(abs_debt_noncurrent, 0))
              / inventory_real_estate
    END                                                                 AS debt_to_inventory,
    -- Converts sitting in the current bucket are a near-term liquidity call.
    CASE WHEN convertible_current > 0
         THEN (cash_unrestricted + marketable_securities) / convertible_current
    END                                                                 AS liquid_cover_of_current_converts
FROM v_balance_sheet;

-- ---------------------------------------------------------------------
-- v_facility_headroom :: Headroom = min(C_fac, BB_t) - D_SPE
-- Capacity comes from the footnote R-files, not XBRL.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_facility_headroom AS
WITH latest AS (
    SELECT DISTINCT ON (period_end, facility_name) *
    FROM   debt_facilities
    ORDER  BY period_end, facility_name, ingested_at DESC
),
-- The consolidated TOTAL block in the footnote reports only "Outstanding,
-- current" and "Net Carrying Amount"; it has no explicit noncurrent
-- outstanding line. Taking outstanding_noncurrent at face value there
-- understates drawn debt by the whole noncurrent balance (9% utilization
-- instead of ~24%). Falling back to net_carrying_amount recovers it, and is
-- a no-op for the group and per-facility rows, which do carry the line.
drawn_parts AS (
    SELECT *,
           COALESCE(outstanding_current, 0)                              AS drawn_cur,
           COALESCE(outstanding_noncurrent, net_carrying_amount, 0)      AS drawn_noncur
    FROM   latest
)
SELECT
    period_end,
    facility_group,
    facility_name,
    borrowing_capacity * scale_factor                                   AS capacity,
    (drawn_cur + drawn_noncur) * scale_factor                           AS drawn,
    (COALESCE(borrowing_capacity, 0) - drawn_cur - drawn_noncur) * scale_factor
                                                                        AS headroom,
    CASE WHEN NULLIF(borrowing_capacity, 0) IS NOT NULL
         THEN (drawn_cur + drawn_noncur) / borrowing_capacity
    END                                                                 AS utilization,
    wtd_avg_rate
FROM drawn_parts;

-- ---------------------------------------------------------------------
-- v_listing_current :: newest snapshot per listing, joined to dimensions
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_listing_current AS
SELECT DISTINCT ON (s.address_token)
       s.address_token, s.snapshot_date, s.list_price, s.buy_direct_price,
       s.days_on_market, s.listing_state, s.display_badge, s.price_per_sqft,
       d.city, d.state, d.zip, d.msa_key, d.latitude, d.longitude,
       d.sqft_living, d.year_built, d.bedrooms, d.bathrooms,
       d.first_seen, d.first_list_price
FROM   listing_snapshots s
JOIN   listing_dim       d USING (address_token)
ORDER  BY s.address_token, s.snapshot_date DESC;

-- ---------------------------------------------------------------------
-- v_inventory_aging :: framework aging brackets [0,90) [90,180) [180,270) [270+)
-- Homes held >90 days carry elevated lower-of-cost-or-NRV writedown risk.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_inventory_aging AS
SELECT
    msa_key,
    snapshot_date,
    CASE
        WHEN days_on_market <  90 THEN '000-089'
        WHEN days_on_market < 180 THEN '090-179'
        WHEN days_on_market < 270 THEN '180-269'
        ELSE                           '270-plus'
    END                                     AS age_bucket,
    COUNT(*)                                AS listings,
    SUM(list_price)                         AS carrying_list_value,
    AVG(days_on_market)::numeric(10,1)      AS avg_dom
FROM   v_listing_current
WHERE  days_on_market IS NOT NULL
GROUP  BY msa_key, snapshot_date, age_bucket;

-- ---------------------------------------------------------------------
-- v_price_cuts :: cut depth measured against OUR first observed price,
-- because originalListPriceCents is null while a listing is active.
--   delta_cut = (P_first - P_current) / P_first
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_price_cuts AS
SELECT
    c.address_token,
    c.msa_key,
    c.snapshot_date,
    c.first_list_price,
    c.list_price                                        AS current_list_price,
    c.days_on_market,
    (c.first_list_price - c.list_price)                 AS cut_amount,
    CASE WHEN NULLIF(c.first_list_price, 0) IS NOT NULL
         THEN (c.first_list_price - c.list_price) / c.first_list_price
    END                                                 AS cut_depth,
    (c.list_price < c.first_list_price)                 AS has_cut,
    -- observation window matters: a cut can only be seen after first_seen
    (c.snapshot_date - c.first_seen)                    AS observed_days
FROM v_listing_current c
WHERE c.list_price IS NOT NULL AND c.first_list_price IS NOT NULL;

-- ---------------------------------------------------------------------
-- v_msa_cut_summary :: price-cut frequency and median depth per MSA
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_msa_cut_summary AS
SELECT
    msa_key,
    snapshot_date,
    COUNT(*)                                                     AS active_listings,
    AVG(CASE WHEN has_cut THEN 1.0 ELSE 0.0 END)                 AS cut_frequency,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cut_depth)
        FILTER (WHERE has_cut)                                   AS median_cut_depth,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_on_market)  AS median_dom,
    SUM(current_list_price)                                      AS total_list_value
FROM   v_price_cuts
GROUP  BY msa_key, snapshot_date;

-- ---------------------------------------------------------------------
-- v_km_input :: Kaplan-Meier survival input over holding duration.
-- A listing that vanished from the sitemap is an EVENT (cleared);
-- one still listed on the latest snapshot is RIGHT-CENSORED.
--   S(t) = P(T_hold > t)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_km_input AS
WITH last_obs AS (
    SELECT DISTINCT ON (address_token)
           address_token, snapshot_date, days_on_market, listing_state
    FROM   listing_snapshots
    ORDER  BY address_token, snapshot_date DESC
),
resolved AS (
    SELECT DISTINCT ON (address_token)
           address_token, event_date, event_type
    FROM   listing_resolution_events
    WHERE  event_type = 'DISAPPEARED'
    ORDER  BY address_token, event_date DESC
),
max_snap AS (SELECT MAX(snapshot_date) AS d FROM listing_snapshots)
SELECT
    l.address_token,
    d.msa_key,
    l.days_on_market                            AS duration_days,
    (r.address_token IS NOT NULL)               AS event_observed,  -- TRUE = cleared
    (r.address_token IS NULL)                   AS censored,
    l.listing_state,
    l.snapshot_date                             AS last_observed_on
FROM       last_obs l
JOIN       listing_dim d USING (address_token)
LEFT JOIN  resolved   r USING (address_token)
CROSS JOIN max_snap m
WHERE l.days_on_market IS NOT NULL;

-- ---------------------------------------------------------------------
-- v_msa_vs_national :: delta MOS = MOS_msa - MOS_national
-- Redfin metro tracker carries MONTHS_OF_SUPPLY directly.
-- ---------------------------------------------------------------------
-- Every filter below pins is_seasonally_adjusted = FALSE. Redfin ships both
-- an adjusted and a raw row per period/region/property type; without the pin
-- each metro appears twice and every average is silently double-counted.
CREATE OR REPLACE VIEW v_msa_vs_national AS
WITH national AS (
    SELECT period_begin,
           AVG(months_of_supply) AS mos_national,
           AVG(median_dom)       AS dom_national
    FROM   redfin_metro_metrics
    WHERE  property_type = 'All Residential'
      AND  is_seasonally_adjusted = FALSE
    GROUP  BY period_begin
)
SELECT
    m.period_begin,
    m.region,
    m.months_of_supply,
    n.mos_national,
    m.months_of_supply - n.mos_national      AS delta_mos,
    m.median_dom,
    m.median_dom - n.dom_national            AS delta_dom,
    m.price_drops,
    m.avg_sale_to_list,
    m.inventory,
    m.homes_sold,
    -- Pending-to-active ratio: forward demand proxy
    CASE WHEN NULLIF(m.inventory, 0) IS NOT NULL
         THEN m.pending_sales / m.inventory
    END                                      AS pending_to_active
FROM      redfin_metro_metrics m
JOIN      national n USING (period_begin)
WHERE     m.property_type = 'All Residential'
  AND     m.is_seasonally_adjusted = FALSE;

-- ---------------------------------------------------------------------
-- v_macro_latest :: newest value per macro series + the mortgage spread
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_macro_latest AS
SELECT DISTINCT ON (metric_key)
       metric_key, date, value
FROM   macro_ts_metrics
ORDER  BY metric_key, date DESC;
