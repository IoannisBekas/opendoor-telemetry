# Dashboard

Three files, no build toolchain:

| File | Does |
| :--- | :--- |
| `export.py` | Reads the analytical views out of Postgres into one JSON payload |
| `template.html` | The page. Carries a single `/*__DATA__*/null` placeholder |
| `build.py` | Substitutes the JSON into the template, trimming the scatter cloud to 1,600 points |

## Rebuild

```bash
PG_DSN="postgresql://..." python dashboard/export.py build/dash.json
python dashboard/build.py dashboard/template.html build/dash.json build/dashboard.html
```

Numbers are never hand-copied into the page — every figure on screen comes out
of the database through `export.py`, so a stale dashboard is impossible as long
as the ingest ran.

## Design constraints

Palette and type follow [`../docs/brand_identity.md`](../docs/brand_identity.md).
Two rules from that document are load-bearing here:

- **`#0040E6` never carries text.** It measures 2.21:1 on the dark card surface.
  It appears only as a fill (the ticker chip) and in the background wash.
  `#1C85E8` is the readable accent.
- **The categorical ramp is `#1C85E8 / #D95926 / #199E70 / #9085E9`**, validated
  against the `#16203A` surface. Slots 1–3 clear the all-pairs gate, so the
  scatter never uses more than three; slot 4 is adjacent-pair only.

Series caps are enforced in the page, not just documented. The three-year
months-of-supply chart names three metros and folds the remaining four into a
range band rather than drawing seven lines. Every bubble in the clearance
scatter is direct-labelled, with a placement loop that flips and nudges labels
until none overlap — identity never rides on colour alone.

Charts are hand-drawn inline SVG. No charting library is loaded: the shapes are
simple, and a CDN dependency would add weight and a failure mode for nothing.

## Provenance is the layout

Each panel carries an uppercase source tag — `SEC EDGAR XBRL`,
`EDGAR FOOTNOTE R-FILE`, `REDFIN DATA CENTER`, `OPENDOOR SITEMAP`. The point of
this project is that none of it costs anything, so which free source each number
came from is information the reader needs, not decoration.
