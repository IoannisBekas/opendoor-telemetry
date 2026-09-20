# Higgsfield.ai Prompt Library — `$OPEN` Dashboard Motion Assets

Generative background video and hero banners for the Opendoor telemetry dashboard.
Palette tokens referenced here are defined in [`brand_identity.md`](brand_identity.md).

**Design constraint that governs every prompt below:** these are *backgrounds*.
Charts, KPI cards and dense numeric tables sit on top of them. A background that
wins attention has failed. Section 4 encodes that as hard limits.

---

## 1. The readability contract

Any asset generated from this library must satisfy all five:

| Rule | Spec | Why |
| :--- | :--- | :--- |
| **Luminance band** | Keep 90% of frame pixels between **12% and 18%** relative luminance | Keeps `#EEF2F8` body text above 13:1 contrast everywhere on the frame |
| **Luminance drift** | ≤ **4 percentage points** change over any 2-second window | Prevents text appearing to "pulse" as the loop plays underneath it |
| **Dead zone** | Centre **60% × 55%** of frame stays near-uniform, no salient subject | That rectangle is where the card grid lands |
| **Edge weighting** | Visual interest confined to outer thirds, corners, and lower edge | Reads as depth without competing with content |
| **Saturation ceiling** | No region above **55% saturation** | Stops the background from clashing with categorical chart hues |

Enforce at composite time with a scrim — `rgba(10, 16, 32, 0.55)` minimum — plus
`backdrop-filter: blur(18px)` on cards. The scrim is not optional; it is what makes
the WCAG ratios in `brand_identity.md` §4 hold for *any* generated frame.

---

## 2. Shared parameter block

Apply to all four prompts unless overridden.

```yaml
model:            Higgsfield Cinema Studio (text-to-video)
aspect_ratio:     16:9          # dashboard background
                  21:9          # hero banner variant
resolution:       3840x2160     # downscale to 1920x1080 for delivery
frame_rate:       24 fps        # cinematic cadence; motion reads as intentional
duration:         8-10 s        # loop point at 8s, see section 5
motion_intensity: 2 / 10        # critical - the default is far too strong
lens:             40mm          # near-neutral; avoids wide-angle distortion
                                # pulling the eye to frame edges
aperture:         f/4.0         # mild depth separation, no heavy bokeh churn
color_profile:    16-bit, low-contrast / log-like grade
seed:             locked per asset, recorded in the filename
```

### Universal negative prompt

Paste into the negative field for every generation:

```
text, letters, numbers, watermark, logo, signage, UI elements, charts, graphs,
people, faces, vehicles in motion, animals, high contrast, harsh specular
highlights, lens flare, bloom, god rays, strobing, flickering, rapid luminance
change, fast camera movement, whip pan, shaky handheld, rolling shutter,
heavy film grain, noise, chromatic aberration, vignetting, busy texture,
cluttered composition, dense foliage detail, centered focal subject,
saturated colors, neon, magenta, orange sky, sunset glare, fisheye distortion,
morphing geometry, warping architecture, duplicated windows, melting edges
```

Rationale for the less obvious entries: `centered focal subject` protects the
dead zone; `rapid luminance change` protects the drift limit; `morphing geometry`
and `duplicated windows` suppress the temporal-coherence artefacts that
architectural generations are especially prone to.

---

## 3. The prompts

### Prompt A — Suburban Modern Architecture

Twilight aerial over contemporary American suburbia. The literal subject matter
of Opendoor's business; best for the hero banner and the landing view.

```
Cinematic aerial drone sweep over a contemporary American suburban
neighborhood at blue hour, twenty minutes after sunset. Clean modern
architecture with flat and low-pitched rooflines, crisp rectilinear geometry,
wide manicured lawns and quiet streets. Warm interior lights glow softly
through windows at low intensity, scattered and irregular across the
neighborhood. Deep navy and cobalt blue atmospheric haze settles between the
houses. Overcast, fully diffused sky with no visible sun and no specular
highlights. Muted desaturated palette of slate, navy, and cool grey with
restrained warm accents from the windows only. Slow smooth forward tracking
shot at constant altitude, drifting gently to the left. Shallow parallax
between foreground rooftops and the distant treeline. 4K photorealistic,
soft cinematic grade, low contrast, calm and still.
```

| Parameter | Value |
| :--- | :--- |
| Camera | Slow dolly forward + gentle lateral drift |
| Motion intensity | 2/10 |
| Lens / aperture | 35mm, f/4.0 |
| Lighting | Blue-hour ambient, fully diffused, no key |
| Aspect | 21:9 hero · 16:9 background |
| Duration | 10s |
| Extra negatives | `sunset, golden hour, orange sky, bright windows, sun flare, pool reflections, palm trees` |

> Blue hour rather than golden hour is deliberate: sunset pushes the frame
> straight past the saturation ceiling and the luminance band.

---

### Prompt B — Algorithmic Market Data & Digital Mapping

Abstract isometric city lattice. Reads as the AVM / pricing-model layer.
Best behind the MSA heatmap and regional views.

```
Abstract three-dimensional isometric city grid rendered as a minimal
wireframe topology. Thin luminous cobalt blue lines trace streets and parcel
boundaries across a dark navy void. Simple extruded rectangular volumes
suggest buildings without surface detail. Small glowing nodes pulse very
slowly at irregular intersections. Faint contour lines ripple outward like a
topographic elevation map. Sparse thin data streams travel slowly along the
grid lines. Clean high-tech corporate aesthetic, generous negative space,
architectural precision. Deep navy background, cobalt and soft cyan
linework, no fill colors. Slow continuous orbital camera movement around the
grid at a shallow angle. Subtle atmospheric depth fade toward the horizon.
4K, crisp vector-like rendering, low contrast, calm.
```

| Parameter | Value |
| :--- | :--- |
| Camera | Slow orbit, shallow angle, constant radius |
| Motion intensity | 2/10 |
| Lens / aperture | 50mm, f/5.6 (flatter, keeps lines crisp) |
| Lighting | Self-emissive linework only, no external source |
| Aspect | 16:9 |
| Duration | 8s (designed to loop) |
| Extra negatives | `dense grid, circuit board, matrix rain, green tint, hexagons, HUD, targeting reticle, glowing floor` |

> Keep the grid sparse. "Dense grid" in the negatives matters more than it
> looks — a dense lattice creates high-frequency detail that fights every
> chart gridline placed above it.

---

### Prompt C — Ambient Hero Loop

The safest asset. Near-abstract, architectural light only. Use as the default
global background behind dense data views.

```
Seamless ambient abstract background of soft architectural shadows drifting
slowly across a smooth dark slate surface. Gentle gradients of deep navy and
charcoal blue blend without hard edges. Faint refracted light bends through
an unseen glass panel, casting soft elongated geometric shapes that move
almost imperceptibly. Subtle volumetric haze adds depth. Extremely low
contrast, matte finish, no reflections, no visible light source. Minimal
composition with large areas of near-uniform tone. Very slow lateral camera
drift, barely perceptible. 4K, clean, quiet, meditative, designed to sit
behind foreground content.
```

| Parameter | Value |
| :--- | :--- |
| Camera | Near-static, minimal lateral drift |
| Motion intensity | 1/10 |
| Lens / aperture | 85mm, f/2.8 (compression flattens the field) |
| Lighting | Indirect ambient only |
| Aspect | 16:9 and 21:9 |
| Duration | 8s, seamless loop |
| Extra negatives | `sharp shadows, hard edges, high contrast, bright highlights, sun shafts, moving objects, texture detail` |

> This is the one to default to. If a data view feels cluttered, swap
> whatever is behind it for Prompt C.

---

### Prompt D — Inventory Flow Abstract

Slow particle drift standing in for acquisition → holding → disposition.
Use behind the unit-economics waterfall and the Kaplan-Meier survival view.

```
Abstract visualization of slow directional flow. Small soft-edged
rectangular particles drift steadily from left to right across a deep navy
field, varying subtly in size and opacity. Particles move at different
speeds creating gentle parallax layers. A faint horizontal band of slightly
lighter tone suggests a channel or corridor. Occasional particles fade out
and dissolve smoothly. Soft cobalt blue and muted slate tones, low
saturation. Generous empty space between elements. Extremely smooth constant
motion with no acceleration. Locked-off camera, no movement. Soft focus
falloff toward the frame edges. 4K, minimal, calm, low contrast.
```

| Parameter | Value |
| :--- | :--- |
| Camera | Locked off (all motion is in-frame) |
| Motion intensity | 2/10 |
| Lens / aperture | 50mm, f/2.0 |
| Lighting | Flat, even, no directional source |
| Aspect | 16:9 |
| Duration | 8s, seamless loop |
| Extra negatives | `swirling, turbulence, explosion, radial burst, particles toward camera, depth of field pulsing, bokeh balls` |

> `particles toward camera` is essential — z-axis motion reads as an alert
> and will pull focus off the chart every time it loops.

---

## 4. Camera, lighting and parameter reference

### Camera moves, ranked by suitability

| Move | Intensity | Use | Verdict |
| :--- | :--- | :--- | :--- |
| Locked off | 0 | Prompt D | Safest |
| Slow lateral drift | 1 | Prompt C | Safest |
| Slow dolly forward | 2 | Prompt A | Good |
| Slow orbit | 2 | Prompt B | Good |
| Crane up / down | 3 | Hero only | Acceptable for a non-looping banner |
| Dolly zoom, crash zoom, FPV, whip pan, Snorricam | 6+ | — | **Never.** Built for narrative, destroys readability |

### Lighting

- **Diffused / overcast only.** No key light, no directional sun.
- **Blue hour beats golden hour** for every asset in this library.
- Practical lights (windows, nodes) stay **under 30% of peak frame luminance**.
- No specular highlights — they blow past the luminance band instantly.

### Aspect and delivery

| Target | Aspect | Delivery |
| :--- | :--- | :--- |
| Dashboard background | 16:9 | 1920×1080, H.264/VP9, ~2 Mbps |
| Hero banner | 21:9 | 2560×1080 |
| Ultrawide dashboard | 21:9 | 3440×1440 |
| Poster fallback | — | First frame as WebP, for `prefers-reduced-motion` and slow links |

Always ship the poster frame. Autoplaying video must be `muted`, `playsinline`,
and gated behind `prefers-reduced-motion: no-preference`.

---

## 5. Looping

Generate 8s at 24fps (192 frames), then in post:

1. Cut the last 12 frames.
2. Cross-dissolve the final 12 frames into the first 12.
3. Verify no luminance step at the seam — it should be invisible under the scrim.

Prompts C and D are written for this (locked/near-locked camera, no narrative
arc). Prompt A does **not** loop cleanly because forward dolly accumulates
parallax; use it as a one-shot hero, or reverse-and-append for a 20s ping-pong.

---

## 6. QC checklist

Before shipping any generated asset:

- [ ] Luminance histogram sits inside the 12–18% band (sample 20 frames)
- [ ] No 2s window drifts more than 4 percentage points
- [ ] Centre 60%×55% is free of salient detail
- [ ] Peak saturation under 55%
- [ ] No text, logos or faces anywhere in the sequence
- [ ] Loop seam invisible at 1× and 0.25× speed
- [ ] Body text over the composite measures ≥ 7:1 contrast
- [ ] Poster frame exported
- [ ] Seed and prompt version recorded in the filename

Suggested naming: `open-bg-{promptletter}-{seed}-{aspect}-v{n}.mp4`
e.g. `open-bg-C-882741-16x9-v2.mp4`
