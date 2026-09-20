# Higgsfield run-sheet

Everything needed to generate the assets yourself, in the order you would run
them. I cannot execute these: Higgsfield requires an account login and spends
credits, so the run has to be yours.

Full prompt library and the readability contract: [`higgsfield_prompts.md`](higgsfield_prompts.md).
This sheet is the operational subset — copy, paste, generate, drop in.

---

## Before you start: which page are these for?

| Page | Takes background assets? |
| :--- | :--- |
| Dark dashboard (`/`) | **Yes.** Already runs a native canvas ground; video is a drop-in replacement. |
| Economist page (`/economist`) | **No.** See the note at the end. |

So every asset below targets the dark dashboard only.

---

## Shared settings

Apply to all three runs unless a run overrides it.

```
Model            Higgsfield Cinema Studio, text-to-video
Aspect ratio     16:9
Resolution       3840x2160, delivered downscaled to 1920x1080
Frame rate       24 fps
Duration         8 s
Motion intensity 2 / 10          <- the default is far too strong
Lens             40 mm
Aperture         f/4.0
Grade            16-bit, low contrast, log-like
```

### Negative prompt — paste into every run

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

---

## Run 1 — `ambient-c` · the default ground

Generate this one first. If you only generate one asset, make it this.

**Seed:** `882741` · **Camera:** near-static, minimal lateral drift ·
**Motion:** 1/10 · **Lens:** 85 mm, f/2.8

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

**Extra negatives:** `sharp shadows, hard edges, high contrast, bright highlights, sun shafts, moving objects, texture detail`

---

## Run 2 — `ambient-b` · the data ground

For the market-clearance and facility sections, if you want the ground to
change between sections rather than run one loop throughout.

**Seed:** `410238` · **Camera:** slow orbit, shallow angle, constant radius ·
**Motion:** 2/10 · **Lens:** 50 mm, f/5.6

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

**Extra negatives:** `dense grid, circuit board, matrix rain, green tint, hexagons, HUD, targeting reticle, glowing floor`

> Keep the lattice sparse. `dense grid` matters more than it looks — a dense
> lattice puts high-frequency detail directly behind every chart gridline.

---

## Run 3 — `hero-a` · optional, 21:9 only

Only if you want a banner above the fold. Does not loop cleanly — forward
dolly accumulates parallax — so use it as a one-shot, or reverse-and-append
for a 20 s ping-pong.

**Seed:** `176604` · **Aspect:** 21:9 · **Duration:** 10 s ·
**Camera:** slow dolly forward with gentle lateral drift · **Lens:** 35 mm, f/4.0

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

**Extra negatives:** `sunset, golden hour, orange sky, bright windows, sun flare, pool reflections, palm trees`

> Blue hour, not golden hour. Sunset blows straight past the saturation
> ceiling and the luminance band.

---

## Post-processing — do this before dropping in

1. **Loop the seam** (runs 1 and 2): cut the last 12 frames, cross-dissolve
   them into the first 12, check for a luminance step at the join.
2. **Export a poster frame** as WebP. Non-negotiable — it serves
   `prefers-reduced-motion` and slow connections.
3. **Encode** H.264 or VP9 at roughly 2 Mbps. These are near-static; a higher
   bitrate buys nothing.
4. **Name** `ambient-{letter}-{seed}-{aspect}-v{n}.mp4`,
   e.g. `ambient-c-882741-16x9-v1.mp4`.

## QC before shipping

- [ ] Luminance histogram inside 12–18% (sample 20 frames)
- [ ] No 2-second window drifts more than 4 percentage points
- [ ] Centre 60% × 55% free of salient detail
- [ ] Peak saturation under 55%
- [ ] No text, logos or faces anywhere in the sequence
- [ ] Loop seam invisible at 1× and 0.25×
- [ ] Body text over the composite measures ≥ 7:1

---

## Where it drops in

Put the files next to `docs/index.html`, then make the swap described in
[`higgsfield_prompts.md` §0](higgsfield_prompts.md) — replace the
`<canvas id="bg">` with a `<video id="bg">`, **add the scrim**, and delete the
`ambientGround()` block from `dashboard/template.html`.

The scrim is the step people skip. The 12–18% luminance band assumes
`rgba(10,16,32,.55)` sitting between the video and the content. Without it the
measured contrast figures in `brand_identity.md` §4 no longer hold and light
text over a bright frame becomes unreadable.

---

## Why the Economist page gets none of this

That page is a printed-page idiom: cream stock, ink, a red flag, flat charts.
Its "hero" is already the flag, the headline and the standfirst — that is how
the original does it, and it is the strongest part of the layout.

Generative video behind those charts would fight the form on every axis. It
would add a luminance floor under text that currently sits at 13–17:1, put
motion behind small multiples that are meant to be compared at a glance, and
introduce depth into a design whose whole argument is flatness.

There is no version of a background asset that improves it, so I have not
proposed one.
