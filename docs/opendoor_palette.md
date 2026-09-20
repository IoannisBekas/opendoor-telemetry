# Opendoor-brand palette — validation record

The brand blue was **sampled from the supplied logo files**, not guessed. Both
resolve to the same value:

| File | Dominant colour | Share |
| :--- | :--- | :--- |
| App icon (600x600) | `#1B85E8` | 88.8% |
| Wordmark (420x420) | `#1B86E8` | 2.7% of frame, all of the mark |

That matches the `#1C85E8` accent previously extracted from Opendoor's live
site CSS, so three independent sources agree.

## The brand blue cannot carry text

Measured against candidate light grounds:

| Ground | `#1B85E8` contrast |
| :--- | :--- |
| `#FFFFFF` | 3.77:1 |
| `#F4F7FB` (chosen) | **3.51:1** |
| `#EEF3F9` | 3.38:1 |

Above the 3:1 floor for marks and fills, below the 4.5:1 needed for body text.
So `#1B85E8` is the identity colour — the masthead bar, figure rules, fills —
and a darker step, `#0F6FC9` at 4.72:1, does the work in charts. This is the
same trap as `#0040E6` on the dark page, one step lighter.

## Final palette

| Token | Hex | Role |
| :--- | :--- | :--- |
| `--brand` | `#1B85E8` | Identity. Fills and rules only, never text |
| `--paper` | `#F4F7FB` | Page ground, cool not cream |
| `--card` | `#FFFFFF` | Panel surface |
| `--ink` | `#0F2340` | Headings — 14.64:1 |
| `--body` | `#2C3A4E` | Body text |
| `--muted` | `#5A6B82` | Captions, axes |
| `--accent` | `#0F6FC9` | Emphasis, chart series 1 |

### Categorical, validated

```
1  #0F6FC9  blue
2  #D9622C  orange
3  #0E8F70  teal-green
4  #7A4FC0  violet   (adjacent-pair forms only)
```

```
all-pairs, 3 slots   worst CVD dE 8.6 (protan) · normal vision 18.9 · all >=3:1
adjacent,  4 slots   worst CVD dE 8.6 (protan) · normal vision 25.4 · all >=3:1
```

Both report ALL CHECKS PASS with no warnings against `#F4F7FB`.

### Sequential ramp — inventory aging

Ordered measure, so a single hue, light to dark. Monotonic.

| Step | Hex | Lightness | Contrast |
| :--- | :--- | :--- | :--- |
| Under 90 days | `#A8CDEF` | 58.2% | 1.55:1 |
| 90-179 | `#5FA3DC` | 33.8% | 2.52:1 |
| 180-269 | `#1B76C4` | 17.2% | 4.41:1 |
| 270+ | `#0B4E8A` | 7.4% | 7.91:1 |

The lightest step sits under 3:1; the relief rule is satisfied because every
bar carries a visible count and share label.

## Moving off the Economist idiom

The first draft of this page used The Economist's language: cream `#FDF9F0`
ground, `#E3120B` red, serif body with sans charts. It was rejected for
looking too much like the original, and the whole palette was rebuilt rather
than recoloured. Three things changed:

- **Ground**: warm cream to cool blue-white. This is the change that does most
  of the work.
- **Accent**: Economist red to Opendoor blue. No red appears anywhere.
- **Type**: their pairing is serif body plus sans charts. That is inverted
  here — Fraunces carries display only, echoing the sturdy serif of the
  Opendoor wordmark, and Public Sans does body, data and chart furniture.

Panels also gained a white card surface, where the Economist idiom keeps
everything flat on the paper.

---

## Appendix — the Economist draft's findings

Retained because the contrast finding is reusable.

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
