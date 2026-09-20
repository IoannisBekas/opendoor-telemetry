# Opendoor Telemetry (`$OPEN`)

Zero-cost ingestion pipeline for the Opendoor Technologies institutional
research framework. Every paid enterprise feed in the original data-source
matrix (Parcl Labs, CoreLogic, Attom, Bloomberg B-PIPE) is replaced with a
free public source.

| Framework need | Original (paid) | Replacement (free) | Status |
| :--- | :--- | :--- | :--- |
| Financials & debt facilities | Paid fundamentals API | SEC EDGAR XBRL `companyfacts` | Working |
| Borrowing base & per-facility rates | Bloomberg / manual | EDGAR footnote R-files | Working |
| MLS microstructure | CoreLogic / MLS feeds | Redfin Data Center bulk TSV | Working |
| Macro & mortgage | Paid terminal | FRED (free key) | Working |
| Property telemetry | Parcl Labs / Attom | Opendoor sitemap + page payloads | Working |
| Convertible bond pricing | FINRA TRACE / B-PIPE | — | **No free substitute**, see below |

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

- **`SEC_USER_AGENT`** — required, must contain a contact email. The SEC
  rejects generic agents with HTTP 403. Config fails fast if it is missing.
- **`FRED_API_KEY`** — free, from <https://fredaccount.stlouisfed.org/apikeys>
- **`PG_DSN`** — PostgreSQL 14+. TimescaleDB is optional and auto-detected.

Create the schema:

```bash
python -m opendoor_telemetry.cli init-db
```

---

## Usage

Check any source end to end **without a database**:

```bash
python -m opendoor_telemetry.cli verify sec
python -m opendoor_telemetry.cli verify footnotes
python -m opendoor_telemetry.cli verify listings --limit 5
```

Ingest:

```bash
python -m opendoor_telemetry.cli ingest sec
python -m opendoor_telemetry.cli ingest footnotes --limit 8
python -m opendoor_telemetry.cli ingest redfin --dataset metro
python -m opendoor_telemetry.cli ingest fred
python -m opendoor_telemetry.cli ingest listings
python -m opendoor_telemetry.cli ingest all
```

### Suggested cadence

| Source | Cadence | Runtime |
| :--- | :--- | :--- |
| `listings` | Daily, off-peak | ~60 min (3,540 URLs at 1 req/s) |
| `redfin --dataset metro` | Weekly | ~2 min (111 MB, cached on Last-Modified) |
| `redfin --dataset weekly` | Weekly | ~10 min (830 MB) |
| `fred` | Daily | seconds (incremental) |
| `sec` / `footnotes` | Quarterly, after each 10-Q/10-K | ~1 min |

---

## Dashboards

Two readings of identical data, from the same export:

| | |
| :--- | :--- |
| **Dark operator view** | <https://ioannisbekas.github.io/opendoor-telemetry/> |
| **Economist idiom, with explanations** | <https://ioannisbekas.github.io/opendoor-telemetry/economist/> |

The second is written for a reader who follows markets but not iBuying: a
"how to read this" note under every heading, hover definitions on each metric,
a linked glossary, and a sentence explaining each number that looks odd. Its
palette was re-derived from scratch for a light ground and re-validated —
see [`docs/economist_palette.md`](docs/economist_palette.md).

Served by GitHub Pages from `docs/`. Rebuild it from `dashboard/` — see
[`dashboard/README.md`](dashboard/README.md). Every figure is read out of
Postgres at build time; nothing is hand-entered, so the page cannot drift from
the data.

The ambient background is a native canvas layer implementing Prompts B and C
from [`docs/higgsfield_prompts.md`](docs/higgsfield_prompts.md) — no video
service, no external asset. That document's §0 has measured contrast figures
and the drop-in swap if you generate Higgsfield video later.

### Publishing a refresh

```bash
PG_DSN=... python dashboard/export.py build/dash.json
python dashboard/build.py dashboard/template.html build/dash.json docs/index.html
python dashboard/build.py dashboard/economist_template.html build/dash.json docs/economist/index.html
git commit -am "refresh dashboards" && git push
```

Pages rebuilds in about 30 seconds.

---

## Verified end to end

The full pipeline was run against PostgreSQL 16 from a clean database —
schema, all four network sources, idempotency re-runs, and every view.
**31/31 checks passed.** See [`tests/`](tests/README.md) to reproduce.

| Stage | Result |
| :--- | :--- |
| Schema | 10 tables, 11 views |
| SEC XBRL | 717 facts; all six balance-sheet assertions matched (2026-06-30) |
| Footnote R-files | 38 facility rows across 3 filings, **0 parse exceptions** |
| Redfin metro | 10,782 rows, 7 regions, 4,792 seasonally-adjusted rows retained |
| Listings | 40 snapshots, DOM populated, `first_list_price` preserved on re-ingest |
| Full sweep | 3,534 of 3,541 listings captured in ~59 min; 1,200 inside the six target metros |
| Idempotency | Re-running every source produced no duplicates |

Live facility picture it produces for 2026-06-30:

```
facility                                       capacity         drawn      util    rate
TOTAL                                     $7,450,000,000  $1,762,000,000   23.7%       -
  Asset-Backed Senior Facilities          $4,200,000,000  $1,416,000,000   33.7%       -
  Asset-backed Mezzanine Term Debt        $3,250,000,000    $350,000,000   10.8%       -
    Term Debt Facility 2021-S3            $1,000,000,000    $625,000,000   62.5%   3.75%
    Revolving Facility 2019-2               $450,000,000    $291,000,000   64.7%   6.50%
    Term Debt Facility 2020-M1            $3,000,000,000    $200,000,000    6.7%  12.50%
    Term Debt Facility 2022-M1              $250,000,000    $150,000,000   60.0%  12.50%
```

That rate column is the point: senior paper at 3.75–6.58% against mezzanine
at 12.50% is the cost-of-funds input for the WACC-vs-inventory-yield spread,
and none of it exists in XBRL.

> **One parsing subtlety, handled in `v_facility_headroom`.** The footnote's
> consolidated TOTAL block reports only "Outstanding, current" and "Net
> Carrying Amount" — it has no noncurrent outstanding line. Read literally,
> TOTAL utilization comes out at 9.3% while its own sub-groups sum to
> ~$1.77B drawn. The view falls back to `net_carrying_amount` for that row,
> which yields 23.7% and cross-checks to within 1% of senior + mezzanine
> (the residual is unamortised issuance costs).

---

## What the audit changed

Five things were verified against live endpoints and contradicted the
original design. Each one would have produced silently wrong data.

**1. Borrowing base is not in XBRL.** There is no `us-gaap` tag for it, and
`companyfacts.json` exposes only the `dei`/`us-gaap`/`ecd` taxonomies with all
dimensions collapsed — so no per-facility detail and no capacity at all.
`edgar_footnotes.py` parses the rendered footnote tables instead, which yields
total capacity, the senior/mezzanine split, **and** per-facility weighted-average
interest rates. Report numbering shifts between filings, so it matches on
`ShortName` rather than a hardcoded `R45.htm`.

**2. XBRL tag usage drifts.** `LongTermDebt` and `LongTermDebtCurrent` stop
after 2021, replaced by `LongTermLineOfCredit` and `LinesOfCreditCurrent`.
Reading a fixed tag returns nulls for half the history, so every concept
resolves through an ordered fallback chain.

**3. The Redfin weekly file is not where the docs imply.**
`redfin_market_tracker/weekly_...` returns **403**. The live path is
`redfin_covid19/weekly_housing_market_data_most_recent.tsv000.gz` (830 MB).
The metro and weekly feeds also have different schemas — 58 columns keyed
`REGION`/`TABLE_ID` versus 40 keyed `REGION_NAME`/`REGION_ID` — hence two
parsers and two tables.

**4. Redfin ships two rows per period.** One seasonally adjusted, one raw.
On the live file, 4,792 of 10,782 target-market rows collide unless
`is_seasonally_adjusted` is part of the primary key — omitting it discards
~44% of the series. Every view pins it to `FALSE` to avoid double-counting.

**5. No headless browser is needed.** The plan called for Playwright.
Opendoor server-renders both a JSON-LD block and a `__NEXT_DATA__` payload
into the HTML, carrying `daysOnMarket`, `listPrice`, `buyDirectPrice`,
`listingState`, lat/lon and more with no JavaScript executed. The scraper is
plain `httpx` plus a regex, which removes the Chromium dependency entirely.

### The baseline was not national

`v_msa_vs_peers` (formerly `v_msa_vs_national`) averages `months_of_supply`
across `redfin_metro_metrics` — but `redfin_bulk.py` filters the bulk file down
to the six target metros *before* loading, so that table never contains anything
else. The average was therefore the **peer-group average of the Opendoor
concentration markets**, published under the label "vs national".

Both dashboards said "vs national" and both were wrong. The view, the export
and both pages now say peer average. A genuine national baseline needs Redfin's
national tracker ingested as a separate table and joined in; widening this
average would not produce one.

### A sitemap URL bug worth knowing

Opendoor publishes unit numbers unescaped, e.g.
`/properties/4747-Puritan-Cir-#-523-Tampa-FL-33617/aid_...`. An HTTP client
reads that `#` as the fragment delimiter and requests only
`/properties/4747-Puritan-Cir-`, which 404s. `_normalize_loc()` percent-encodes
it to `%23`, which returns 200.

This accounted for 8 of the 15 failures on the first full sweep. The remaining
7 have an empty address slug (`/properties//aid_...`) — an upstream defect with
no client-side fix. They stay in `parse_exceptions` rather than vanishing.

### The price-cut trap

`listingHistory[].originalListPriceCents` is **null while a listing is
active** — it is only populated on historical `SOLD` rows. Price-cut depth
therefore cannot be read off the page. `listing_snapshots` is append-only and
`listing_dim.first_list_price` holds the first price we ever observed, which
is what `v_price_cuts` measures against. A consequence worth knowing: cut
depth is only measurable from the day the pipeline first sees a listing, so
the series needs a few weeks of history before it is meaningful.

### MSA assignment is geographic

Opendoor listings carry no CBSA code. Matching on city name fails for the
suburbs that make up most of a metro (Lithia Springs GA is Atlanta; Allen TX
is DFW), and a state-level fallback would wrongly pull Raleigh-Durham into
Charlotte and Jacksonville into Tampa. `config.market_for_point()` assigns by
haversine distance from a metro centroid, with radii in `config/markets.yml`.
Listings outside every radius keep `msa_key = NULL` rather than being guessed
into the wrong market.

---

## Politeness and terms

- **SEC** caps automated access at 10 req/s and requires a descriptive
  User-Agent with a contact email. `SEC_RATE_LIMIT` defaults to 8.
- **Opendoor** is fetched at 1 req/s. `robots.txt` publishes the sitemaps this
  pipeline reads and allows `/properties/` and `/homes/`; it disallows `/api/`
  (except `/api/agent/v1/`). That blocklist is enforced structurally in
  `http.py` — a disallowed path raises `PermissionError` rather than being
  fetched.
- Opendoor's `robots.txt` also declares `Content-Signal: ai-train=no`. This
  pipeline performs quantitative market analysis and trains no model on the
  content, which is consistent with that signal. If you intend to use the
  scraped text for model training, that signal says not to.
- **Redfin** bulk files are published for public use; cite Redfin as the
  source in anything you publish.

---

## Known gap: FINRA TRACE

The framework calls for secondary-market pricing and YTM on the convertible
senior notes. There is no free TRACE API; FINRA's public portal is HTML-only
and its terms prohibit scraping. This is the one item with no zero-cost
substitute, and it is deliberately not implemented.

Partial mitigation from XBRL: `ConvertibleDebtNoncurrent` went to 0 at
2025-12-31 while `ConvertibleDebtCurrent` stands at $194M as of 2026-06-30 —
the converts have rolled into current maturity, which `v_capital_structure`
surfaces as `liquid_cover_of_current_converts`. That captures the liquidity
exposure even without market pricing.

---

## Layout

```
config/markets.yml          6 target MSAs, verified Redfin region names, centroids
sql/001_schema.sql          tables
sql/002_views.sql           framework formulas as views
src/opendoor_telemetry/
  config.py                 settings, market roster, geographic assignment
  http.py                   rate limiting, retry, conditional cache, robots enforcement
  db.py                     upserts, run bookkeeping, parse_exceptions
  cli.py                    entry point
  sources/
    edgar_facts.py          XBRL companyfacts, fallback chains
    edgar_footnotes.py      footnote R-files, borrowing base
    redfin_bulk.py          streaming bulk TSV
    fred_macro.py           macro series + derived spreads
    opendoor_listings.py    sitemap + page payload scraper
docs/
  brand_identity.md         palette, glass surfaces, WCAG contrast
  higgsfield_prompts.md     4 motion prompts + readability contract
tests/
  e2e_test.py               full pipeline against a live Postgres
dashboard/
  export.py template.html build.py    the published dashboard
```

### Operational notes

- **Parse failures are rows, not crashes.** Unmatched footnote labels and
  failed listing fetches land in `parse_exceptions` so upstream layout drift
  is visible. Check it after each run:
  `SELECT source, reason, count(*) FROM parse_exceptions GROUP BY 1,2;`
- **Listings are never deleted.** A listing leaving the sitemap is written to
  `listing_resolution_events` as a candidate sale/delist, which is what feeds
  the Kaplan-Meier event/censoring split in `v_km_input`.
- **Restatements coexist.** `sec_facts` is keyed by accession; `v_sec_latest`
  picks the newest `filed` per period.
