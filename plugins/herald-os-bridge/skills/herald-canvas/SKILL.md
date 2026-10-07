---
name: herald-canvas
description: Make and edit pictures in Herald Canvas, the layered image editor in Herald OS - posters, banners, thumbnails, collages and photo fixes through the canvas tool, plus the .comp project format and every adjustment setting
metadata:
  hermes:
    tags: [herald-os, canvas, images, design, photo, poster, layers]
---

# Herald Canvas

Herald Canvas is the image editor built into Herald OS: layers, folders, masks, blend modes and
adjustment layers, drawn on the GPU. Use it whenever the person wants a picture made or changed:
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
3. **Arrange.** `set_layer layer="band" x=… y=… width=…` (one side alone keeps the proportions),
   `rotation=-8`, `opacity=0.8`, `blend="Multiply"`, `order=top`, `visible=false`,
   `folder="Background"`. `group layers="band,glow" name="Hero"` makes a folder.
4. **Grade.** `add_adjustment kind="Hue/Saturation" settings={"saturation": 20}`. An adjustment
   changes everything below it; with `clip=true` only the layer right below.
5. **Look before you say it is done.** `canvas action=preview` answers with a PNG `file`; view it,
   then fix what is off. Do this after every few steps on anything that matters.
6. **Deliver.** `canvas action=export to="~/Desktop/gig-poster.png"` (or `.jpg` with
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
- Put text on calm areas or over a gradient fade, and check contrast in the preview.
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
canvas action=add_layer color="#ffb347" x=72 y=1180 width=240 height=8 name="Accent rule"
canvas action=preview
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
- **Exposure**: `exposureSettings.exposure` −20…20 stops, `offset` −1…1, `gamma` 0.01…10.
- **Gradient Map**: `gradientMapSettings.shadows` and `highlights` as `{"red", "green", "blue"}`
  0…1, `reversed`.
- **Grain**: `grainSettings.amount` 0…100, `size` 0.1…100, `roughness` 0…100, `seed`.
- **Invert**: no settings.
- **Black & White**: `blackWhiteSettings.reds`, `yellows`, `greens`, `cyans`, `blues`,
  `magentas` −200…300 (how light each colour turns), `tint`, `tintHue` 0…360, `tintSaturation`
  0…100.
- **Color Balance**: `colorBalanceSettings` with `shadowCyanRed`, `shadowMagentaGreen`,
  `shadowYellowBlue`, the same three for `mid…` and `highlight…`, each −100…100 (positive is
  towards red, green, blue), and `preserveLuminosity`.
- **Gaussian Blur**: `blurRadius` 0.1…250 pixels.
- **Motion Blur**: `motionAngle` −90…90, `motionDistance` 1…2000.
- **Add Noise**: `noiseAmount` 0.1…400, `noiseGaussian`, `noiseMonochromatic`, `noiseSeed`.

Quick recipes: warmer, `Color Balance` with `midCyanRed` +10 and `midYellowBlue` −15; moodier,
`Curves` with a lowered midpoint plus `Hue/Saturation saturation=-25`; brighter,
`Exposure exposure=0.4`; vintage, `Gradient Map` from deep blue to cream at opacity 0.35 with
blend Soft Light, plus `Grain amount=20`.

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
  `levels` and `curves`). Keep fields you do not understand exactly as they were.

The same files open in Compositor on a Mac.
