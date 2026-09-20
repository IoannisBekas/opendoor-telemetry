# Opendoor Brand Identity — Dashboard Design System

Extracted for the `$OPEN` institutional telemetry dashboard. Dark-mode glassmorphic target.

---

## 1. Provenance

Third-party brand-colour aggregators disagree on Opendoor's blue — three different
"official" values are in circulation:

| Source | Claimed primary | Verdict |
| :--- | :--- | :--- |
| brandcolorcode.com | `#147BD1` | Stale — not present in live CSS |
| colorswall | `#1B84E6` | Close to the live accent, not exact |
| Published brand guidelines (2021 refresh) | `#033CCE`, `#2056BC` | Documented, superseded in product |
| **Live opendoor.com CSS (fetched 2026-09-20)** | **`#0040E6`** | **Authoritative — what actually ships** |

Everything below is taken from the live stylesheet, not from secondary sources.
The documented guideline values are retained as a cross-reference in §5.

---

## 2. Core palette

| Token | Hex | RGB | Role |
| :--- | :--- | :--- | :--- |
| `--od-blue-primary` | `#0040E6` | 0, 64, 230 | Brand anchor, primary action, key series |
| `--od-blue-accent` | `#1C85E8` | 28, 133, 232 | Links, hover, chart series 1 |
| `--od-blue-deep` | `#03476B` | 3, 71, 107 | Deep teal, chart series 2 |
| `--od-navy` | `#1D2C4C` | 29, 44, 76 | Dark surface base |
| `--od-ink` | `#2C2C2B` | 44, 44, 43 | Near-black ground, light-mode text |
| `--od-slate` | `#525975` | 82, 89, 117 | Muted text, gridlines, axes |
| `--od-neutral` | `#ECEAE6` | 236, 234, 230 | Warm light neutral |
| `--od-tint` | `#F3F9FE` | 243, 249, 254 | Pale wash, light-mode surface |
| `--od-success` | `#22C55E` | 34, 197, 94 | Positive contribution margin |

### Derived semantic colours

Opendoor's shipped palette has no red. These are added for the dashboard's
risk semantics, hue-matched to sit beside the brand blue without clashing:

| Token | Hex | Role |
| :--- | :--- | :--- |
| `--od-warning` | `#E8A13C` | Aging inventory 180–270d, MOS 4–6 months |
| `--od-danger` | `#E66767` | Negative contribution margin, MOS > 6, 270d+ inventory |
| `--od-terracotta` | `#F7AF98` | Accent from the guideline extended palette |

---

## 3. Dark-mode glassmorphic surfaces

Built on `--od-navy` rather than pure black, so the brand blue stays legible
against the ground.

```css
:root {
  /* brand */
  --od-blue-primary: #0040E6;
  --od-blue-accent:  #1C85E8;
  --od-blue-deep:    #03476B;
  --od-navy:         #1D2C4C;
  --od-ink:          #2C2C2B;
  --od-slate:        #525975;
  --od-neutral:      #ECEAE6;
  --od-tint:         #F3F9FE;

  /* semantic */
  --od-success:   #22C55E;
  --od-warning:   #E8A13C;
  --od-danger:    #E66767;
  --od-terracotta:#F7AF98;

  /* light-mode defaults */
  --bg-base:      var(--od-tint);
  --bg-surface:   #FFFFFF;
  --text-primary: var(--od-ink);
  --text-muted:   var(--od-slate);
  --hairline:     rgba(29, 44, 76, 0.12);
}

:root[data-theme="dark"],
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    /* layered ground: radial brand wash over a near-black navy */
    --bg-base: #0A1020;
    --bg-gradient:
      radial-gradient(1200px 600px at 20% -10%, rgba(0, 64, 230, 0.18), transparent 60%),
      radial-gradient(900px 500px at 90% 10%, rgba(28, 133, 232, 0.10), transparent 55%),
      #0A1020;

    /* glass */
    --glass-fill:        rgba(29, 44, 76, 0.38);
    --glass-fill-raised: rgba(29, 44, 76, 0.55);
    --glass-border:      rgba(236, 234, 230, 0.10);
    --glass-highlight:   rgba(236, 234, 230, 0.18);
    --glass-blur:        18px;
    --glass-shadow:      0 8px 32px rgba(3, 12, 32, 0.45);

    --text-primary: #EEF2F8;
    --text-muted:   #9AA5BF;
    --hairline:     rgba(236, 234, 230, 0.08);
  }
}

.od-card {
  background: var(--glass-fill);
  backdrop-filter: blur(var(--glass-blur)) saturate(140%);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(140%);
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  box-shadow: var(--glass-shadow);
}

/* 1px top highlight sells the glass edge */
.od-card::before {
  content: "";
  position: absolute; inset: 0 0 auto 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--glass-highlight), transparent);
}
```

---

## 4. Contrast (WCAG 2.1)

Measured against the dark glass card fill composited over `#0A1020`
(effective card background ≈ `#16203A`).

Measured, not estimated.

| Foreground | Hex | Ratio vs card | Verdict |
| :--- | :--- | :--- | :--- |
| Primary text | `#EEF2F8` | 14.36:1 | AAA — body and figures |
| Warning | `#E8A13C` | 7.37:1 | AA — all sizes |
| Success | `#22C55E` | 7.08:1 | AA — all sizes |
| Muted text | `#9AA5BF` | 6.54:1 | AA — labels, axes |
| Critical | `#E66767` | 4.99:1 | AA — all sizes |
| Accent blue | `#1C85E8` | 4.28:1 | AA large text and marks |
| **Primary blue `#0040E6`** | `#0040E6` | **2.21:1** | **Fails as text.** Fills, strokes, and buttons with white labels only |

The last row is the one that matters in practice: `#0040E6` is the brand
anchor but cannot carry text on a dark ground. Use `--od-blue-accent`
(`#1C85E8`) for anything a reader has to read.

### Categorical chart ramp — validated

```
1. #1C85E8   Opendoor accent blue
2. #D95926   burnt orange
3. #199E70   aqua
4. #9085E9   violet          (adjacent-pair forms only: bars, lines, stacks)
```

Verified with the data-viz palette validator against the `#16203A` card
surface — lightness band, chroma floor, CVD separation, normal-vision floor
and contrast all pass. Slots 1–3 additionally clear the **all-pairs** gate,
so they are the cap for scatter and bubble charts; slot 4 is adjacent-pair
only.

> **Correction.** The ramp originally published here (`#1C85E8` · `#E8A13C` ·
> `#22C55E` · `#9A7BE8` · `#03476B` · `#F7AF98`) was asserted to be
> colourblind-checked. It is not. Run against the validator it fails four of
> five gates — worst case green↔amber at **ΔE 4.8 for protanopia**, well under
> the ΔE 8 target, meaning red-green colourblind readers cannot separate two
> adjacent series. `#03476B` and `#F7AF98` also fall below the chroma floor
> (they read as grey) and `#03476B` sits at 1.63:1 contrast. It is replaced by
> the four-slot ramp above.

Past four series, fold into "Other" or facet into small multiples — never
generate a fifth hue. Never encode a value by hue alone: pair with position,
shape, or a direct label.

### Status palette — reserved

Never reused as a categorical series, and always shipped with an icon or
label rather than colour alone.

| State | Hex | Use |
| :--- | :--- | :--- |
| Good | `#22C55E` | Positive contribution margin, MOS < 4, headroom ample |
| Warning | `#E8A13C` | MOS 4–6, inventory 180–270d, utilization > 60% |
| Critical | `#E66767` | MOS > 6, inventory 270d+, negative margin |

---

## 5. Cross-reference: published guideline palette

Retained for print and partner collateral, where the 2021 guideline values remain canonical:

`#E3ECF8` · `#141314` · `#A5B0BF` · `#F7AF98` · `#033CCE` · `#504948` · `#9D7C76` · `#2056BC`

`#033CCE` and `#0040E6` are within ~4% perceptual distance; either reads as
"Opendoor blue". The live value is preferred for screen so the dashboard matches
the product.

---

## 6. Typography and motion

| Element | Spec |
| :--- | :--- |
| Display / headings | Inter or Söhne, 600, −0.02em tracking |
| Body | Inter 400, 15–16px, 1.55 line height |
| Numerals | **Tabular lining figures** (`font-variant-numeric: tabular-nums`) — non-negotiable for price and DOM columns |
| Mono | JetBrains Mono / ui-monospace for tickers and accession numbers |
| Card radius | 14px; 10px for inner elements |
| Motion | 180–240ms, `cubic-bezier(.2,.8,.2,1)`; respect `prefers-reduced-motion` |

Background video must sit behind a scrim: `rgba(10, 16, 32, 0.55)` minimum,
so the contrast ratios in §4 hold. See `higgsfield_prompts.md` §4.
