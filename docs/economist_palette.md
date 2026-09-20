# Economist-idiom palette — validation record

The dark dashboard's palette is not reused here. Nothing carried over: the
dark-surface hexes were stepped for `#16203A` and every one of them fails on a
cream ground. This page was re-derived from scratch against `#FDF9F0` and
re-validated.

## What changed, and why

### The authentic Economist palette fails its own ground

Running The Economist's published chart colours against `#FDF9F0`:

| Colour | Result |
| :--- | :--- |
| `#006BA2` blue | passes |
| `#3EBCD2` cyan | **1.8–2.14:1 contrast** — below the 3:1 floor |
| `#EBB434` yellow | **1.80:1 contrast** — below the floor |
| `#379A8B` teal | **chroma 0.094** — below the floor, reads grey |

This is not a mistake on their part. Those colours are designed for ink on
cream paper at print resolution, where hairline marks and direct labels carry
the identity and the screen contrast rule does not apply. On a backlit display
they are too pale to anchor a mark.

### Darkening the cyan does not work

The obvious fix — darken cyan and yellow until they clear 3:1 — collapses the
palette. A darkened cyan sits on top of the blue:

| Candidate | Blue↔cyan separation |
| :--- | :--- |
| `#17869B` | ΔE 8.7 normal vision — **below the 15 floor** |
| `#127A8F` | ΔE 6.2 normal vision — **far below** |

Two blues that a full-colour reader cannot separate is worse than a contrast
warning. The fix had to be hue spread, not lightness.

### Final palette

Categorical, in fixed order. Slots 1–3 clear the **all-pairs** gate, so they
are the cap for scatter and bubble forms; slot 4 is adjacent-pair only.

| Slot | Hex | Name |
| :--- | :--- | :--- |
| 1 | `#006BA2` | Economist blue |
| 2 | `#E3120B` | Economist red |
| 3 | `#2E7D32` | green |
| 4 | `#7B4EA8` | violet (bars, lines, stacks only) |

```
all-pairs, 3 slots   worst CVD ΔE 9.1 (deutan) · normal vision 19.2 · all ≥3:1
adjacent,  4 slots   worst CVD ΔE 9.1 (deutan) · normal vision 27.3 · all ≥3:1
```

Both report ALL CHECKS PASS with no warnings.

**Gold `#B07A0F` was cut.** It sits at ΔE 4.7 against the green under
protanopia — a red-green colourblind reader loses the pair. It survives only as
a standalone status colour where no green is adjacent.

### Sequential ramp — inventory aging

Aging buckets are *ordered*, not categorical, so they take a single-hue ramp
rather than four unrelated colours. This is a correction to the dark
dashboard, which wrongly used categorical hues for an ordered measure.

| Step | Hex | Lightness | Contrast |
| :--- | :--- | :--- | :--- |
| Under 90 days | `#A9CBE0` | 56.5% | 1.62:1 |
| 90–179 | `#6FA3C4` | 33.6% | 2.59:1 |
| 180–269 | `#357FA8` | 18.8% | 4.21:1 |
| 270+ | `#00537F` | 7.7% | 7.86:1 |

Monotonic, as a sequential ramp must be. The lightest step is under 3:1 against
cream; the relief rule is satisfied because every bar carries a visible count
and share label beside it.

### Text and rules

| Role | Hex | Contrast on `#FDF9F0` |
| :--- | :--- | :--- |
| Headline ink | `#121212` | 17.83:1 |
| Body | `#2B2B2B` | 13.47:1 |
| Muted / source lines | `#5B6B73` | 5.27:1 |
| Gridlines | `#D8D2C6` | decorative only, never carries meaning |

## Single-theme, deliberately

This page does not ship a dark variant. The Economist idiom is a printed-page
one — cream stock, ink, a red flag — and inverting it produces something that
is neither Economist nor the dark dashboard. Every colour is painted
explicitly so the page holds on any host background. The dark glassmorphic
treatment still exists at the site root; this is a second reading of the same
data, not a replacement.
