-- =====================================================================
-- Opendoor Telemetry :: base schema
-- PostgreSQL 14+.  TimescaleDB is optional and auto-detected.
-- Safe to re-run (idempotent).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS od;
SET search_path = od, public;

-- ---------------------------------------------------------------------
-- 1. SEC XBRL company facts  (source: edgar_facts.py)
-- ---------------------------------------------------------------------
-- One row per (tag, period_end, accession).  Restatements arrive as a new
-- accession for the same period_end; `filed` breaks the tie downstream.
CREATE TABLE IF NOT EXISTS sec_facts (
    tag             text        NOT NULL,
    period_end      date        NOT NULL,
    period_start    date,
    accession       text        NOT NULL,
    form            text        NOT NULL,
    frame           text,                    -- e.g. CY2026Q2I
    fy              integer,
    fp              text,
    unit            text        NOT NULL DEFAULT 'USD',
    value           numeric     NOT NULL,
    filed           date        NOT NULL,
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tag, period_end, accession)
);
CREATE INDEX IF NOT EXISTS ix_sec_facts_tag_period ON sec_facts (tag, period_end DESC);
CREATE INDEX IF NOT EXISTS ix_sec_facts_frame      ON sec_facts (frame);

-- ---------------------------------------------------------------------
-- 2. Credit facility detail  (source: edgar_footnotes.py)
-- ---------------------------------------------------------------------
-- Borrowing base capacity has NO us-gaap XBRL tag, and companyfacts.json is
-- dimensionally collapsed, so per-facility capacity/rate can only come from
-- the rendered footnote R-files listed in each FilingSummary.xml.
CREATE TABLE IF NOT EXISTS debt_facilities (
    accession               text    NOT NULL,
    period_end              date    NOT NULL,
    facility_group          text,             -- Asset-Backed Senior Facilities, Mezzanine, ...
    facility_name           text    NOT NULL, -- Revolving Facility 2018-2, TOTAL, ...
    borrowing_capacity      numeric,
    outstanding_current     numeric,
    outstanding_noncurrent  numeric,
    issuance_costs          numeric,
    net_carrying_amount     numeric,
    wtd_avg_rate            numeric,          -- decimal fraction: 0.0725 = 7.25%
    scale_factor            numeric NOT NULL DEFAULT 1,  -- 1e6 when header says "$ in Millions"
    source_report           text,             -- e.g. R45.htm
    ingested_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (accession, period_end, facility_name)
);
CREATE INDEX IF NOT EXISTS ix_debt_fac_period ON debt_facilities (period_end DESC);

-- Layout drift lands here instead of crashing the run.
CREATE TABLE IF NOT EXISTS parse_exceptions (
    id          bigserial PRIMARY KEY,
    source      text        NOT NULL,
    accession   text,
    context     text,
    raw_label   text,
    raw_value   text,
    reason      text,
    seen_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_parse_exc_source ON parse_exceptions (source, seen_at DESC);

-- ---------------------------------------------------------------------
-- 3. Opendoor listing telemetry  (source: opendoor_listings.py)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS listing_dim (
    address_token    uuid        PRIMARY KEY,
    slug             text,
    street           text,
    city             text,
    state            text,
    zip              text,
    msa_key          text,        -- joins config/markets.yml key
    latitude         numeric,
    longitude        numeric,
    year_built       integer,
    bedrooms         integer,
    bathrooms        numeric,
    sqft_living      integer,
    sqft_lot         integer,
    dwelling_type    text,
    first_seen       date        NOT NULL,
    last_seen        date        NOT NULL,
    first_list_price numeric,     -- synthetic original: first price ever observed
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_listing_dim_msa ON listing_dim (msa_key, last_seen DESC);

-- Append-only daily snapshot.  This table is the ONLY reliable source of
-- price-cut depth: listingHistory originalListPriceCents is null while a
-- listing is active, so cuts must be diffed from our own observations.
CREATE TABLE IF NOT EXISTS listing_snapshots (
    snapshot_date       date        NOT NULL,
    address_token       uuid        NOT NULL,
    list_price          numeric,
    buy_direct_price    numeric,
    buy_direct_savings  numeric,
    days_on_market      integer,
    listing_state       text,       -- ON_THE_MARKET, PENDING, ...
    display_badge       text,
    price_per_sqft      numeric,
    est_monthly_payment numeric,
    http_status         integer,
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, address_token)
);
CREATE INDEX IF NOT EXISTS ix_snap_token ON listing_snapshots (address_token, snapshot_date DESC);

-- A listing leaving the sitemap is a candidate sale/delist, never a delete.
CREATE TABLE IF NOT EXISTS listing_resolution_events (
    address_token           uuid    NOT NULL,
    event_date              date    NOT NULL,
    event_type              text    NOT NULL,  -- DISAPPEARED | REAPPEARED | STATE_CHANGE
    prior_state             text,
    new_state               text,
    last_list_price         numeric,
    days_on_market_at_event integer,
    PRIMARY KEY (address_token, event_date, event_type)
);

-- ---------------------------------------------------------------------
-- 4. Redfin bulk metrics  (source: redfin_bulk.py)
-- ---------------------------------------------------------------------
-- Two distinct upstream schemas, therefore deliberately two tables.
-- metro tracker = 58 cols keyed REGION/TABLE_ID (monthly, by property type)
CREATE TABLE IF NOT EXISTS redfin_metro_metrics (
    period_begin            date    NOT NULL,
    period_end              date    NOT NULL,
    period_duration         integer,
    region                  text    NOT NULL,
    table_id                integer NOT NULL,
    state_code              text,
    property_type           text    NOT NULL,
    property_type_id        integer,
    -- Part of the key: Redfin publishes a seasonally-adjusted AND a raw row
    -- for the same period/region/property type. Verified on the live file:
    -- 4,792 of 10,782 target-market rows collide without this column, so
    -- omitting it silently discards ~44% of the series.
    is_seasonally_adjusted  boolean NOT NULL,
    median_sale_price       numeric,
    median_sale_price_yoy   numeric,
    median_list_price       numeric,
    median_list_price_yoy   numeric,
    median_ppsf             numeric,
    median_list_ppsf        numeric,
    homes_sold              numeric,
    homes_sold_yoy          numeric,
    pending_sales           numeric,
    new_listings            numeric,
    inventory               numeric,
    inventory_yoy           numeric,
    months_of_supply        numeric,
    median_dom              numeric,
    median_dom_yoy          numeric,
    avg_sale_to_list        numeric,
    sold_above_list         numeric,
    price_drops             numeric,
    off_market_in_two_weeks numeric,
    parent_metro_region     text,
    last_updated            timestamptz,
    PRIMARY KEY (period_begin, region, property_type, table_id, is_seasonally_adjusted)
);
CREATE INDEX IF NOT EXISTS ix_rf_metro_region ON redfin_metro_metrics (region, period_begin DESC);

-- weekly tracker = 40 cols keyed REGION_NAME/REGION_ID (rolling 1w and 4w)
CREATE TABLE IF NOT EXISTS redfin_weekly_metrics (
    period_begin                          date    NOT NULL,
    period_end                            date    NOT NULL,
    region_type                           text    NOT NULL,
    region_name                           text    NOT NULL,
    region_id                             integer NOT NULL,
    duration                              text    NOT NULL,
    adjusted_average_new_listings         numeric,
    average_pending_sales_listing_updates numeric,
    off_market_in_two_weeks               numeric,
    adjusted_average_homes_sold           numeric,
    median_new_listing_price              numeric,
    median_sale_price                     numeric,
    median_days_to_close                  numeric,
    median_new_listing_ppsf               numeric,
    active_listings                       numeric,
    active_listings_yoy                   numeric,
    median_days_on_market                 numeric,
    median_days_on_market_yoy             numeric,
    pct_active_with_price_drops           numeric,
    pct_active_with_price_drops_yoy       numeric,
    age_of_inventory                      numeric,
    weeks_of_supply                       numeric,
    average_sale_to_list_ratio            numeric,
    median_sale_ppsf                      numeric,
    last_updated                          timestamptz,
    PRIMARY KEY (period_begin, region_id, duration)
);
CREATE INDEX IF NOT EXISTS ix_rf_weekly_name ON redfin_weekly_metrics (region_name, period_begin DESC);

-- ---------------------------------------------------------------------
-- 5. Macro time series  (source: fred_macro.py)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS macro_ts_metrics (
    date        date    NOT NULL,
    metric_key  text    NOT NULL,
    value       numeric,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (date, metric_key)
);
CREATE INDEX IF NOT EXISTS ix_macro_key ON macro_ts_metrics (metric_key, date DESC);

-- ---------------------------------------------------------------------
-- 6. Ingestion bookkeeping
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_runs (
    id           bigserial PRIMARY KEY,
    source       text        NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       text        NOT NULL DEFAULT 'RUNNING',
    rows_written integer     NOT NULL DEFAULT 0,
    detail       text
);

-- ---------------------------------------------------------------------
-- 7. Optional TimescaleDB hypertables
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('od.listing_snapshots', 'snapshot_date',
                                  if_not_exists => TRUE, migrate_data => TRUE);
        PERFORM create_hypertable('od.macro_ts_metrics', 'date',
                                  if_not_exists => TRUE, migrate_data => TRUE);
        RAISE NOTICE 'TimescaleDB detected: hypertables created.';
    ELSE
        RAISE NOTICE 'TimescaleDB not installed; using plain tables.';
    END IF;
END $$;
