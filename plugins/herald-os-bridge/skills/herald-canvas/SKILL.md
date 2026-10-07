---
name: herald-canvas
description: Make and edit pictures in Herald Canvas, the layered image editor in Herald OS - posters, banners, thumbnails, collages and photo fixes through the canvas tool, with editable text and shape layers, layer effects (shadows, strokes, glows) and masks, plus the .comp project format and every adjustment setting
metadata:
  hermes:
    tags: [herald-os, canvas, images, design, photo, poster, layers, text, typography, effects, masks]
---

# Herald Canvas

Herald Canvas is the image editor built into Herald OS: layers, folders, masks, blend modes,
adjustment layers, editable text and shapes, drawn on the GPU. The person has the usual tools too
(selections, brush, fill, gradient, transform, crop). Use it whenever the person wants a picture
made or changed:
"make a poster for Saturday's gig", "warm this photo up", "put our logo on these", "make a
YouTube thumbnail". They watch each change appear in the Canvas window, and every change is one
step they can undo there (⌘Z, or `canvas action=undo`).

## The workflow

1. **Start.** `canvas action=new name="Gig poster" width=1080 height=1350 background="#101014"`
   makes a project in `~/Pictures/Herald Canvas/` and opens it; it answers with the `path`. To
   work on something that exists, `canvas action=open path="~/Pictures/photo.jpg"`: an image
   becomes a new project there (the original file is never changed) and the answer gives its
   `path`; a `.comp` project opens as it is. Without `project`, actions work on the image in front.
2. **Build it in layers**, bottom to top. Each `add_layer` lands above the active layer:
   - a picture: `source="~/Downloads/band.jpg"` or `source="https://…"`; it fits inside the canvas,
     centred (`fit=cover` fills it, `fit=none` keeps its own size, or give `x`, `y`, `width`).
   - a colour block: `color="#ff5a36" x=0 y=1100 width=1080 height=250`.
   - a gradient: `gradient="#00000000,#000000cc" angle=90 y=700 height=650` (a fade to dark at
     the bottom, under text).
   - an empty layer to group with others: no source, colour or gradient.
3. **Words.** `add_text content="NIGHT\nMARKET" x=72 y=420 font="Helvetica Neue Bold" size=180
   color="#ffffff"` makes a text layer the person can edit later (double-click it with the Type
   tool). Point text: `x` is its left edge, or its centre with `align=center`, or its right edge
   with `align=right`; `y` is its top. Give `width` for a paragraph that wraps inside a box from
   `x`. `size` is pixels; `tracking` and `leading` add pixels between letters and lines (negative
   tightens a big headline). Fonts are installed families with an optional style ("Avenir Next
   Demi Bold", "Georgia Italic"); a missing font falls back to the system font, so check the
   preview. `set_text layer="Headline" content=… color=…` changes it in place and keeps its size,
   turn and position.
4. **Shapes.** `add_shape kind=rounded x=72 y=900 width=936 height=300 color="#ff5a36"` (a
   rectangle with `radius`, or `kind=rectangle`, `kind=ellipse` for circles and ovals, `kind=line`
   from `x, y` by `width` across and `height` down, `lineWidth` thick). Panels behind text, rules,
   badges and dots are shapes, not filled boxes: they stay crisp and editable.
5. **Arrange.** `set_layer layer="band" x=… y=… width=…` (one side alone keeps the proportions),
   `rotation=-8`, `opacity=0.8`, `blend="Multiply"`, `order=top`, `visible=false`,
   `folder="Background"`. `group layers="band,glow" name="Hero"` makes a folder.
6. **Grade.** `add_adjustment kind="Hue/Saturation" settings={"saturation": 20}`. An adjustment
   changes everything below it; with `clip=true` only the layer right below. Change it later with
   `set_adjustment layer="Hue/Saturation" settings={"saturation": 35}` (merged over what it has;
   `canvas action=layers` shows each adjustment's `settings`).
7. **Polish.** `set_effects layer="Headline" effects={"shadow": {"distance": 8, "blur": 16,
   "opacity": 0.45}}` adds a drop shadow; strokes, glows, inner shadows and colour overlays work the
   same way (see Layer effects below). `mask layer="Photo" mask=hide` and friends show or hide
   parts of a layer without erasing anything.
8. **The canvas.** `resize width=1080 height=1920 anchor=top` grows or cuts the canvas around an
   anchor (layers keep their pixels, so nothing is lost); `resize scale=0.5`, or `image=true` with
   a width, scales everything instead. `crop x=0 y=135 width=1080 height=1080` keeps a box.
9. **Look before you say it is done.** `canvas action=preview` answers with a PNG `file`; view it,
   then fix what is off. Do this after every few steps on anything that matters.
10. **Deliver.** `canvas action=export to="~/Desktop/gig-poster.png"` (or `.jpg` with
   `quality=0.9`, `.webp`; `scale=0.5` for half size). Replacing a file needs `overwrite=true`,
   and the person is asked first. Projects save themselves after every change.

`canvas action=layers` lists everything with ids, kinds, placement and clipping: use it to find
names and to check what is where. Ids are stable; names are friendlier (the topmost layer with a
name wins).

## Good design habits

- Ask one question when the brief is thin (size, words, colours); otherwise choose and say what
  you chose. Common sizes: Instagram post 1080×1350, story 1080×1920, YouTube thumbnail
  1280×720, A4 print 2480×3508 at 300 ppi, slide 1920×1080.
- Keep a clear hierarchy: one focal image, at most two type sizes, generous margins (about 6% of
  the short side), and a limited palette pulled from the photo.
- Put text on calm areas, over a gradient fade or on a shape panel, and check contrast in the
  preview. Big headlines read best bold with tight tracking; body text wants a paragraph `width`
  of about 60 characters and 1.2 to 1.4 line spacing.
- Prefer adjustment layers to changing pixels: they stay editable, and the person can switch them
  off.
- Name layers for what they are ("Headline", "Sky"), and folder related pieces.
- Never use pictures the person has not given you or asked you to find; mention sources.

## A poster, start to finish

```
canvas action=new name="Night market" width=1080 height=1350 background="#0d0d12"
canvas action=add_layer source="~/Pictures/market.jpg" fit=cover name="Photo"
canvas action=add_adjustment kind="Color Balance" clip=true settings={"midCyanRed": 12, "midYellowBlue": -14, "highlightYellowBlue": -8}
canvas action=add_layer gradient="#0d0d1200,#0d0d12f0" angle=90 y=650 height=700 name="Fade"
canvas action=add_text content="NIGHT\nMARKET" x=72 y=700 font="Helvetica Neue Bold" size=168 leading=-24 tracking=2 color="#fff4e6" name="Headline"
canvas action=set_effects layer="Headline" effects={"shadow": {"distance": 6, "blur": 18, "opacity": 0.5}}
canvas action=add_shape kind=line x=72 y=1100 width=240 lineWidth=8 color="#ffb347" name="Accent rule"
canvas action=add_shape kind=rounded x=72 y=1140 width=600 height=120 radius=24 color="#ffb347" name="Date panel"
canvas action=add_text content="Saturday 9 November · 6 pm till late" x=104 y=1172 width=540 font="Helvetica Neue Medium" size=40 color="#0d0d12" name="Date"
canvas action=preview
canvas action=set_text layer="Headline" size=180
canvas action=export to="~/Desktop/night-market.png"
```

## Blend modes

Normal; Darken, Multiply, Color Burn, Linear Burn; Lighten, Screen, Color Dodge, Linear Dodge
(Add); Overlay, Soft Light, Hard Light, Vivid Light, Linear Light, Pin Light, Hard Mix;
Difference, Exclusion, Subtract, Divide; Hue, Saturation, Color, Luminosity. Multiply darkens
(shadows, paper texture), Screen lightens (glows, light leaks), Overlay and Soft Light add
contrast, Color tints while keeping the detail. Folders are pass-through: their own mode is always
Normal, and their opacity and mask apply to everything inside.

## Adjustment settings

Pass only what you change; the rest keeps its default.

- **Hue/Saturation**: `hue` −360…360, `saturation` −100…100, `lightness` −100…100, `colorize`
  true/false (with colorize, hue picks the tint).
- **Levels**: `levels.channel` RGB, Red, Green or Blue, and `levels.ranges`, four ranges (RGB,
  red, green, blue), each `black` 0…255, `gamma` 0.01…10, `white` 0…255, `outputBlack`,
  `outputWhite`. Give all four ranges when you set them.
- **Curves**: `curves.channels`, four point lists (RGB, red, green, blue) of 2 to 64
  `{"x": 0…255, "y": 0…255}` in increasing x. A gentle S for contrast:
  `[{"x":0,"y":0},{"x":64,"y":52},{"x":192,"y":204},{"x":255,"y":255}]`.
- **Exposure**: `exposureSettings.exposure` −20…20 stops, `offset` −0.5…0.5, `gamma` 0.01…9.99
  (worked in linear light).
- **Gradient Map**: `gradientMapSettings.shadows` and `highlights` as `{"red", "green", "blue"}`
  0…1 or any CSS colour (`"#1b1340"`), `reversed`.
- **Grain**: `grainSettings.amount` 0…100, `size` 0.5…20 pixels, `roughness` 0…100, `seed`.
- **Invert**: no settings.
- **Black & White**: `blackWhiteSettings.reds`, `yellows`, `greens`, `cyans`, `blues`,
  `magentas` −200…300 (how light each colour turns), `tint`, `tintHue` 0…360, `tintSaturation`
  0…100.
- **Color Balance**: `colorBalanceSettings` with `shadowCyanRed`, `shadowMagentaGreen`,
  `shadowYellowBlue`, the same three for `mid…` and `highlight…`, each −100…100 (positive is
  towards red, green, blue), and `preserveLuminosity`.
- **Gaussian Blur**: `blurRadius` 0.1…250 pixels.
- **Motion Blur**: `motionAngle` −90…90 (counterclockwise from horizontal), `motionDistance`
  1…2000 pixels.
- **Add Noise**: `noiseAmount` 0.1…400 (percent), `noiseGaussian`, `noiseMonochromatic`,
  `noiseSeed`.

An adjustment never adds opacity: over transparency it shows nothing, and a blur softens colour
but keeps the edges of what is below it. A mask on an adjustment layer limits where it applies.

Quick recipes: warmer, `Color Balance` with `midCyanRed` +10 and `midYellowBlue` −15; moodier,
`Curves` with a lowered midpoint plus `Hue/Saturation saturation=-25`; brighter,
`Exposure exposure=0.4`; vintage, `Gradient Map` from deep blue to cream at opacity 0.35 with
blend Soft Light, plus `Grain amount=20`; dreamy, `Gaussian Blur blurRadius=12` at opacity 0.4
with blend Screen.

## Layer effects

`set_effects layer=… effects={…}` puts effects on a picture, text or shape layer (not on folders
or adjustment layers). Per effect, an object merged over what the layer has (or over the effect's
defaults when it has none), `true` to add it with its defaults, `false` to remove it, and
`{"enabled": false}` to hide it while keeping its settings. `clear=true` removes them all first.
Sizes and distances are layer pixels; `color` is any CSS colour (or `red`, `green`, `blue` 0…1);
`opacity` is 0…1. The effects follow the layer's own mask, and the layer's opacity and blend mode
apply to the layer and its effects together.

- **shadow** (drop shadow, under the layer): `angle` −360…360, where the light comes from (90 is
  straight above, so the shadow falls straight down; 120 drops it down and to the right),
  `distance` 0…5000, `blur` 0…500 (how soft), `color`, `opacity`. Defaults 90, 20, 20, black, 0.5.
- **innerShadow** (inside the edges, as if cut out): the same fields; defaults 90, 10, 10, black,
  0.5.
- **outerGlow**: `size` 0…500, `color`, `opacity`; defaults 20, white, 0.75.
- **innerGlow**: `size` 0…500, `color`, `opacity`; defaults 10, white, 0.75.
- **stroke**: `size` 0…500, `inside` (false puts it outside the edge, with round corners),
  `color`, `opacity`; defaults 4, black, 1, outside.
- **colorOverlay** (tints the layer, keeping its shape): `color`, `opacity`; defaults red, 1.

Recipes:

- A soft drop shadow for a cut-out photo or a card:
  `effects={"shadow": {"angle": 120, "distance": 18, "blur": 40, "opacity": 0.35}}`.
- A glow on a headline over a dark picture:
  `effects={"outerGlow": {"size": 28, "color": "#ffd27a", "opacity": 0.8}}`.
- Legible white text on a busy photo: `effects={"stroke": {"size": 3, "color": "#111"},
  "shadow": {"distance": 4, "blur": 10, "opacity": 0.6}}`.
- A sticker look: `effects={"stroke": {"size": 14, "color": "#fff"}, "shadow": {"distance": 6,
  "blur": 12, "opacity": 0.3}}`.
- Hide the stroke but keep it for later: `effects={"stroke": {"enabled": false}}`.

## Masks

A mask shows (white) or hides (black) parts of a layer without erasing anything; folders and
adjustment layers take masks too. `mask layer=… mask=<action>`:

- `reveal` or `hide`: a mask showing or hiding everything (replacing one the layer has).
- `revealSelection` or `hideSelection`: from what the person has selected in the Canvas window.
- `invert`, `enable`, `disable` (kept but not used), `remove`.
- `apply`: bake the mask into the pixels and drop it (not for folders or adjustments).
- `unlink`: the mask stays where it is when the layer moves; `link` ties it to the layer again.

Typical use: a vignette is a `Curves` or `Exposure` layer that darkens, with a mask hiding its
centre; a two-tone grade is two adjustments, each masked to its half.

## The .comp format (for writing projects directly)

For many layers at once it can be faster to write a project yourself; Herald Canvas reloads an
open project the moment its files change. A project is a folder `Name.comp` holding
`manifest.json` and `images/`:

```json
{
  "format": "com.compositor.project",
  "version": 11,
  "colorSpace": "sRGB",
  "resolution": 72,
  "documentID": "<UUID>",
  "width": 1080,
  "height": 1350,
  "activeLayerID": "<UUID of a layer>",
  "guides": [],
  "layers": [
    {
      "id": "6F1D…",
      "name": "Photo",
      "isVisible": true,
      "isGroup": false,
      "opacity": 1,
      "blendMode": "Normal",
      "imageFile": "6F1D….png",
      "transform": { "origin": [0, 0], "size": [1080, 1350], "rotation": 0, "flipX": false, "flipY": false, "sampling": "High quality" }
    }
  ]
}
```

Rules that matter (break one and the whole file is refused):

- `layers` run bottom to top. A folder has `"isGroup": true` and no `imageFile`; its children
  carry `"parentID"` and come right after it.
- Ids are uppercase UUIDs, unique. A layer's picture is `images/<ID>.png` (8-bit RGBA PNG) and
  its mask `images/<ID>.mask.png` (8-bit grayscale, white shows), named after the layer exactly.
- `transform.origin` is the top-left corner in canvas pixels, `size` the drawn size (the PNG is
  stretched to it), `rotation` degrees clockwise around the centre, `sampling` "High quality",
  "Smooth" or "Nearest".
- Write every image first, then `manifest.json` last, through a temporary file and a rename, so
  the editor never reads half a project.
- `maskSourceID` clips a layer to another; `adjustment` makes an adjustment layer (no
  `imageFile`; its record needs `kind`, `hue`, `saturation`, `lightness`, `colorize`, plus full
  `levels` and `curves`). `effects` holds the layer effects, one record per effect as listed under
  Layer effects (a missing record means no such effect). An unlinked mask has `"maskLinked": false`
  and its own `maskPlacement` transform. Keep fields you do not understand exactly as they were.
- A text or shape layer is a normal pixel layer (its PNG shows it) with a `text` record
  (`content`, `fontName` as a PostScript name, `fontSize` in pixels, `red`/`green`/`blue` 0…1,
  `alignment` Left, Center or Right, `tracking`, `leading`, and `boxSize` [width, height] for
  paragraph text) or a `shape` record (`kind` Rectangle, Ellipse or Line, `red`/`green`/`blue`,
  `cornerRadius`, and for lines `lineWidth` with `start` and `end` as fractions of the box). The
  PNG must match the record, so prefer `add_text` and `add_shape`, which draw it; painting on such
  a layer turns it into plain pixels.

The same files open in Compositor on a Mac.
