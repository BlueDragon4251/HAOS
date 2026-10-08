# Herald Canvas

Herald Canvas is the image editor built into Herald OS: layers, folders, masks, blend modes,
adjustment layers, layer effects, editable text and shapes, drawn on the GPU. It has the tools you
know from photo editors, a few that run AI models on your computer, and Hermes can work in it with
you: ask for a poster, a thumbnail or "make this photo warmer", and watch each change land as a
step you can undo.

Open it from Applications (`Cmd+Shift+A`, `Super+A` on Linux), from Files ("Edit in Herald Canvas"
on an image), or by asking Hermes. On Herald OS Linux it opens in its own window, three quarters of
the screen wide.

## Opening and saving

- **Projects.** Herald Canvas saves `.comp` projects: a folder holding `manifest.json` and an
  `images/` folder of PNGs (on a Mac the folder shows as one file). The same projects open in
  Compositor on a Mac. A saved project saves itself shortly after each change; File > Save
  Automatically turns that off.
- **Images.** PNG, JPEG, WebP, GIF, BMP, AVIF, SVG and ICO open directly. HEIC, TIFF and camera
  RAW files (DNG, CR2, CR3, NEF, ARW, RAF, ORF, RW2) are converted by the system first: macOS reads
  them all, and on Linux see [Linux notes](#linux-notes). An image opens as a new, unsaved document;
  the file itself is never changed. Drop an image on an open document to place it as a layer.
- **Photoshop documents.** PSD and PSB files open with their layers; see
  [Photoshop documents](#photoshop-documents) for what carries over.
- **Exporting.** File > Export as PNG, JPEG, WebP or PSD. PNGs are written a band at a time, so
  even the largest image never sits whole in memory; WebP is limited to 16,383 pixels a side.
- **Changes from elsewhere.** An open project follows its files on disk. A change Hermes, a script
  or Compositor makes comes in as one step you can undo; if you have unsaved changes too, a bar asks
  whether to keep yours or load theirs.
- **Limits.** A canvas is up to 30,000 pixels a side and 100 million pixels in all. Large images
  are drawn in tiles, and the view only draws what is on screen, so a 12,000 × 9,000 image pans and
  paints smoothly on a Mac.

## Tools

Press a tool's key to pick it; press it again (or with `Shift`) for the other tool in its group.

| Tool | Key | What it does |
| --- | --- | --- |
| Move | `V` | Moves the picked layers; with "Show transform controls", scales and turns them |
| Rectangular and Elliptical Marquee | `M` | Selects a box or an ellipse (`Shift` adds, `Alt` takes away) |
| Lasso and Polygonal Lasso | `L` | Selects freehand, or corner to corner (`Backspace` takes back a corner) |
| Magic Wand and Object Select | `W` | Selects similar colours; Object Select picks the object you click or box (an AI model) |
| Crop | `C` | Crops the canvas, freely or to a ratio, and straightens a tilted picture (`Enter` crops, `Esc` cancels); layers keep their pixels |
| Eyedropper | `I` | Picks a colour from the image |
| Spot Healing Brush and Healing Brush | `J` | Paints over a blemish and fills it from around it; the Healing Brush copies from where you `Alt`-click and takes on the colour around each stroke |
| Brush | `B` | Paints, on the pixels or on the layer's mask |
| Clone Stamp | `S` | Copies from where you `Alt`-click (`Option`-click), following the pointer |
| Eraser | `E` | Erases (on a mask, hides) |
| Paint Bucket and Gradient | `G` | Fills similar colours, or drags a gradient from the gradient editor, in five styles |
| Type | `T` | Click for a line of text, drag a box for a paragraph; click a text layer to edit it |
| Shape | `U` | Draws a rectangle, rounded rectangle, ellipse or line (`Shift` squares it) |
| Hand | `H` (or hold `Space`) | Moves the view |
| Zoom | `Z` | Zooms in (`Alt` out) |

Other keys: `X` swaps the foreground and background colours and `D` resets them; `[` and `]` change
the brush size (the Clone Stamp's, the healing brushes' and the Refine Edge brush's too), with
`Shift` its hardness; the number keys set opacity (`5` is 50%, `4` then `5` quickly is 45%); the
arrow keys nudge the picked layers with the Move tool (`Shift` for 10 pixels).

| Command | macOS | Herald OS Linux |
| --- | --- | --- |
| New, Open, Save, Save As | `Cmd+N`, `Cmd+O`, `Cmd+S`, `Cmd+Shift+S` | `Ctrl` with the same keys |
| Undo, Redo, Toggle Last State | `Cmd+Z`, `Cmd+Shift+Z`, `Cmd+Alt+Z` | `Ctrl` with the same keys |
| Cut, Copy, Copy Merged, Paste | `Cmd+X`, `Cmd+C`, `Cmd+Shift+C`, `Cmd+V` | `Ctrl` with the same keys |
| Fill, with the foreground or background colour | `Shift+F5`, `Alt+Backspace`, `Cmd+Backspace` | `Shift+F5`, `Alt+Backspace`, `Ctrl+Backspace` |
| Free Transform | `Cmd+T` | `Ctrl+T` |
| Select All, Deselect, Reselect, Inverse | `Cmd+A`, `Cmd+D`, `Cmd+Shift+D`, `Cmd+Shift+I` | `Ctrl` with the same keys |
| Select and Mask | `Cmd+Alt+R` | `Ctrl+Alt+R` |
| Feather the selection | `Shift+F6` | `Shift+F6` |
| New Layer, Duplicate (or Layer via Copy), Layer via Cut | `Cmd+Shift+N`, `Cmd+J`, `Cmd+Shift+J` | `Ctrl` with the same keys |
| Group, Ungroup, Clipping Mask | `Cmd+G`, `Cmd+Shift+G`, `Cmd+Alt+G` | `Ctrl` with the same keys |
| Bring Forward, Send Backward (to the front or back with `Shift`) | `Cmd+]`, `Cmd+[` | `Ctrl+]`, `Ctrl+[` |
| Merge Down | `Cmd+E` | `Ctrl+E` |
| Image Size, Canvas Size | `Cmd+Alt+I`, `Cmd+Alt+C` | `Ctrl+Alt+I`, `Ctrl+Alt+C` |
| Auto Tone, Auto Contrast, Auto Color | `Cmd+Shift+L`, `Cmd+Alt+Shift+L`, `Cmd+Shift+B` | `Ctrl` with the same keys |
| Last Filter | `Cmd+Alt+F` | `Ctrl+Alt+F` |
| Zoom in, out, fit, actual pixels | `Cmd+=`, `Cmd+-`, `Cmd+0`, `Cmd+1` | `Ctrl` with the same keys |
| Rulers, Guides, Lock Guides, Snap | `Cmd+R`, `Cmd+;`, `Cmd+Alt+;`, `Cmd+Shift+;` | `Ctrl` with the same keys |
| Export as PNG | `Cmd+Alt+Shift+W` | `Ctrl+Alt+Shift+W` |

## History

The History tab, beside Properties (or Edit > History), lists every step from the top down. The
first row is the document as it opened (or, once old steps were let go to save memory, the earliest
state kept), and the current step is highlighted. Click a step to go back to it: the steps after it
dim and stay until you make a new change, which drops them. Steps Hermes made are marked with a
sparkle, and changes from outside the window (Hermes on a closed project, a script, Compositor)
with a circling arrow. Edit > Toggle Last State flips between the last change and the state before
it, to compare.

## Cropping and straightening

The Crop tool's options hold the box to a ratio: Free, Original, 1:1, 4:5, 3:2, 16:9, 9:16, or
Custom with your own width and height; the swap button turns it between portrait and landscape.
Straighten lets you draw along a horizon or an edge that should be level: the picture turns so it
is, and the box keeps the largest area with no empty corners. `Enter` crops (one step, straightening
included); `Esc` puts everything back. The box snaps to guides and to the canvas's and layers' edges.

## Rulers, guides and snapping

- **Rulers.** View > Rulers shows pixel rulers along the top and left, with a mark following the
  pointer.
- **Guides.** Drag from a ruler to pull out a guide; with the Move tool (or holding `Cmd`, `Ctrl`
  on Linux) drag a guide to move it, or off the canvas to remove it. View > New Guide places one at
  an exact position (or a percentage), View > Clear Guides removes them all and View > Lock Guides
  keeps them still. Guides are saved with the project and never export.
- **Snapping.** With View > Snap on, moves, transforms, crop boxes and marquees snap to guides, the
  canvas's edges and centre, and other layers' edges and centres; View > Snap To picks which.
  Dragging a guide with `Shift` places it without snapping.
- **Smart guides.** While you move a layer, lines show where it lines up with another, and equal
  gaps between layers are labelled with their size (View > Smart Guides).

## Retouching

- **Spot Healing Brush** (`J`): paint over a blemish, a wire or a small object; when you let go it
  is filled from the pixels around it.
- **Healing Brush** (`J` again): `Alt`-click (`Option`-click) a clean area, then paint over what
  should go. The copy keeps its texture, and when you let go its colour and tone are matched to the
  pixels around the stroke, so skin, sky or a wall blends in without a seam.
- **Clone Stamp** (`S`): `Alt`-click where to copy from, then paint: the source follows the pointer
  at the same distance. Aligned keeps that distance from one stroke to the next; turned off, every
  stroke copies from the source point again. Sample copies the layer you paint on or all layers
  together. While you hover, the brush shows the source under it, and a crosshair marks where the
  copy comes from.

Both work through the selection with the brush's size, hardness, opacity and flow, one step a
stroke.

## Filters

The Filter menu changes the active layer's pixels, inside the selection when there is one:

- **Blur:** Gaussian Blur (radius) and Motion Blur (angle, distance).
- **Noise:** Add Noise (amount, uniform or gaussian, monochromatic), Median (radius: removes specks
  and dust) and Reduce Noise (strength, how much detail to keep, colour noise; it smooths flat areas
  and keeps edges).
- **Sharpen:** Unsharp Mask (amount, radius, and a threshold below which differences are left
  alone) and Smart Sharpen (sharpens brightness only, holding back halos and grain).
- **Other:** High Pass (radius), the fine detail on gray: set it to Overlay or Soft Light to sharpen.

Each opens with a preview on the canvas as you change it (on a reduced copy for very large images)
and applies as one step; Filter > Last Filter runs the last one again with the same settings. A
filter changes pixels for good: the Gaussian Blur, Motion Blur and Add Noise adjustment layers do
the same without touching them.

## Select and Mask

Select > Select and Mask refines a selection, or the mask you are painting on, for hair, fur and
soft edges. Around the edge (Radius, with Smart Radius narrowing it where the picture's edge is
crisp), each pixel is worked out again from the colours of what is surely in and surely out near
it; paint with the Refine Edge brush over stray hair to work it out there too (`Alt` takes the
brush back). Smooth, Feather, Contrast and Shift Edge then shape the edge. View shows the result
as an overlay, on black, on white, in black and white, or as marching ants.

Output to the selection, a layer mask, a new layer, or a new layer with a layer mask (the original
is hidden); Decontaminate Colours, for the new layers, takes the background's colour out of the
edge. OK (`Enter`) refines at full size as one step; Cancel (`Esc`) leaves everything as it was.

## Gradients

Click the gradient in the Gradient tool's options to open the editor:

- **Presets:** Foreground to Background, Foreground to Transparent, Black to White, Fade to Black,
  Spectrum, Sunset, Ocean, Copper, Steel and Violet to Orange, then the gradients you saved. Name
  the gradient and press Save to keep it; hover a saved one for its remove button.
- **Stops:** opacity stops sit above the strip and colour stops below it. Click beside the strip to
  add a stop, drag one to move it, drag it away (or press `Delete`) to remove it. A colour stop is
  its own colour, or the foreground or background colour of the moment. The diamond between two
  stops sets where they mix half way.
- **Styles:** linear, radial, angle (a sweep around where you start), reflected (both ways from the
  start) and diamond, with Reverse and Opacity beside them. `Shift` keeps the line to 45° steps.

## Layers

- **Layers and folders.** The Layers panel lists layers top to bottom. Folders pass through: their
  opacity and mask apply to everything inside, and their own blend mode is always Normal. Drag rows
  to reorder them, or `Alt`-click a line between two layers to clip the upper one.
- **Blend modes.** Normal; Darken, Multiply, Color Burn, Linear Burn; Lighten, Screen, Color Dodge,
  Linear Dodge (Add); Overlay, Soft Light, Hard Light, Vivid Light, Linear Light, Pin Light, Hard
  Mix; Difference, Exclusion, Subtract, Divide; Hue, Saturation, Color, Luminosity.
- **Masks.** Layer > Add Mask, or Layer > Layer Mask for Reveal or Hide All, from the selection,
  Invert, Apply, Disable and Unlink. Click a mask's thumbnail to paint on it (black hides, white
  shows); `Cmd`-click (`Ctrl`-click) a thumbnail to load it as a selection.
- **Clipping.** A clipped layer shows only where the layer under it has pixels: text filled with a
  photo, a colour change on one layer.
- **Adjustment layers.** Layer > New Adjustment Layer: Brightness/Contrast, Levels, Curves,
  Exposure; Vibrance, Hue/Saturation, Color Balance, Black & White, Photo Filter, Channel Mixer,
  Color Lookup; Invert, Posterize, Threshold, Gradient Map, Selective Color; Grain, Gaussian Blur,
  Motion Blur and Add Noise. They change everything under them (only the layer below when clipped)
  and stay editable in the Properties panel. Color Lookup loads a 3D `.cube` table (2 to 65 entries
  a side), as grading tools save them, and keeps it in the project. Eight of these are Herald
  Canvas's own: see [Compositor compatibility](#compositor-compatibility) for how Compositor shows
  them.
- **Auto Tone, Auto Contrast and Auto Color.** The Image menu reads the picture under the active
  layer and adds a Levels layer that fixes it: Auto Tone stretches each channel to the full range,
  Auto Contrast stretches all three together so colours keep their balance, and Auto Color also
  takes out a colour cast. The layer stays editable, and its opacity tones it down.
- **Align and distribute.** With the Move tool, the options bar lines the picked layers up by their
  left, centre, right, top, middle or bottom, and spaces three or more evenly (by their edges or
  with equal gaps). "To" picks what they line up with: each other, the selection or the canvas
  (automatic takes the selection when there is one, then each other with several layers, then the
  canvas). Layer > Align and Layer > Distribute do the same. A layer lines up by what it shows, not
  by its transparent margins.
- **Layer styles.** Layer > Layer Style: stroke, drop shadow, inner shadow, outer glow, inner glow
  and colour overlay, on pictures, text and shapes, with their settings in the Properties panel.
  Copy Layer Style takes the active layer's effects; Paste Layer Style puts them on every picked
  layer in place of theirs, and Clear Layer Style takes them off every picked layer, one step each.
- **Text and shapes.** Text layers stay editable: pick them with the Type tool, and change font,
  size, colour, alignment, tracking and leading in the options bar. The font list is the fonts on
  your computer, by their real names. Shape layers change kind, colour, corner radius and line
  width in the Properties panel. Layer > Rasterize turns either into plain pixels.
- **Merging.** Merge Down (`Cmd+E`) draws a layer into the one below; Image > Flatten Image makes
  everything visible one layer.

## AI on your computer

These tools run on your computer; nothing is uploaded. None of the models ships with Herald OS: the
first time you use a tool that needs one, Herald Canvas asks before downloading it, shows its size
and licence, and checks every file against its published SHA-256 before it runs. Models are stored
in `~/.hermes/herald-os/models`, and Edit > AI Models lists them, with Resume for a stopped download
and Remove. They run on the GPU through WebGPU where there is one, and on the processor otherwise
(slower, but they work).

| Tool | Model | Download | Licence |
| --- | --- | --- | --- |
| Layer > Remove Background, Select > Subject | ISNet (general use) | 179 MB | Apache-2.0 |
| Object Select (`W`) | EfficientSAM (tiny) | 41 MB | Apache-2.0 |
| Edit > Content-Aware Fill, Spot Healing Brush (`J`) | none: PatchMatch, written for Herald Canvas | | |

ISNet's weights are published under Apache-2.0, but the DIS5K images it was trained on were released
for research use. The file Herald downloads is the rembg project's ONNX conversion of the authors'
weights, as the authors publish only PyTorch ones.

**Generative fill.** Edit > Generative Fill (on a selection) and Layer > New Generated Layer ask
Hermes to make a picture with the image generation tool of your model provider, and place it where
you asked, masked to the selection. This one does use your provider, and may cost what your plan
charges for images.

## Working with Hermes

Ask in the Hermes window, with your voice, or in the Ask Hermes field at the bottom of the Canvas
window, which sends the image's layers and a preview along. Things that work well:

- "Make an Instagram post for Saturday's market: 1080 by 1350, the photo from my Downloads, the
  date in a panel at the bottom."
- "Make this photo moodier", "warm it up a little", "put the logo in the bottom right corner".
- "Fix the colour cast", "straighten the horizon and crop it to 4:5", "sharpen it a little".
- "Lay out a 12-column grid with 60-pixel margins", "line the three logos up along the bottom and
  space them evenly", "give the subtitle the headline's style".
- "Give it a film look with ~/LUTs/Portra.cube", "lift the shadows with Brightness/Contrast".
- "Remove the background of the product shot", "take the wire out of the sky" (content-aware fill).
- "Export it as a PSD for the printer" or "as a JPEG at half size".

Hermes works through its `canvas` tool, the same commands the command bar and voice reach: new and
open, layers, text, shapes, adjustments (Auto Tone, Contrast and Color too), effects (and copying
them between layers), masks, aligning and distributing, guides, filters, resizing, cropping and
straightening, previews, exports, the history, and the on-device tools. Each change lands in the
open window as you watch, as one step: `Cmd+Z` undoes it, or ask Hermes to undo (several steps at
once if you like). On Herald OS Linux, `herald-os canvas` does the same from a terminal
(`herald-os canvas new Poster 1080x1350`, `herald-os canvas text "Night market"`,
`herald-os canvas align bottom --layers Logo,Badge`, `herald-os canvas filter unsharp mask --amount
120`, `herald-os canvas export ~/Desktop/poster.png`, `herald-os canvas undo --steps 2`). Hermes
never downloads a model: when one is missing it asks you to allow it in the window.

## Compositor compatibility

Herald Canvas reads and writes the `.comp` format (version 11), so a project moves between Herald
Canvas on Linux or a Mac and Compositor on a Mac. Herald holds every value to
the ranges Compositor accepts (it refuses a whole project over one value outside them) and says
which field is wrong when a change would leave a range. Fields it does not use, such as
Compositor's own settings, are kept as they were. Text keeps Compositor's per-letter colour and
font runs: Herald Canvas draws them and keeps them through edits where the edited range allows
(typed letters take the colour of the letter before them). Compositor's Hue/Saturation settings for
single colour ranges are kept in the file, but Herald Canvas draws only the master setting.

Eight adjustments are Herald Canvas's own: Brightness/Contrast, Vibrance, Photo Filter, Channel
Mixer, Selective Color, Posterize, Threshold and Color Lookup. Compositor refuses a project with an
adjustment kind it does not know, so Herald keeps their settings in a field of their own, which
Compositor passes by, beside one of Compositor's kinds that it does read:

| Herald's adjustment | What Compositor shows |
| --- | --- |
| Brightness/Contrast | The same change, as Curves |
| Vibrance | With Vibrance at 0, the same change as Hue/Saturation; otherwise the picture unchanged |
| Photo Filter | Without Preserve Luminosity, the same change as Levels; otherwise the picture unchanged |
| Channel Mixer, Selective Color, Posterize, Threshold, Color Lookup | The picture unchanged (Levels that change nothing) |

A Color Lookup's table is saved in the project as `images/<layer id>.cube`, which Compositor does
not read. If you save the project in Compositor, it keeps the Compositor kinds and drops Herald's
settings and tables, so those layers come back to Herald Canvas as the Curves, Hue/Saturation or
Levels layers Compositor showed.

## Photoshop documents

Herald Canvas reads and writes PSD and PSB files itself (with the ag-psd library, in the
background), and lists anything it approximated once the file is open or written.

- **What opens:** pixel layers with their position, opacity, visibility and blend mode; folders;
  layer and folder masks; clipping; text layers (Photoshop's pixels, and the text, font, size,
  colour, alignment, tracking, leading and colour and font runs, so they can be edited); and the
  layer effects Herald draws (drop and inner shadow, outer and inner glow, colour overlay, stroke).
  Every adjustment layer opens: Brightness/Contrast, Levels, Curves, Exposure, Vibrance,
  Hue/Saturation, Color Balance, Black & White, Photo Filter, Channel Mixer, Color Lookup (with a
  `.cube` table), Invert, Posterize, Threshold, Gradient Map and Selective Color. Herald draws its own
  adjustments with its own maths, so they look close to Photoshop's rather than identical.
- **What changes:** blend modes Herald lacks (Dissolve, Darker Color, Lighter Color) become Normal; a
  folder's own blend mode becomes Pass Through; Color Lookup layers with a `.3dl` or `.look` table
  or a colour profile, and effects (bevel and emboss, satin, gradient and pattern overlays) are left
  out; smart objects,
  shape layers and vector masks become pixels (vector masks only where Photoshop stored them as a
  mask too); gradient maps keep their first and last colours; text that is turned, warped, vertical
  or set in a font this computer lacks stays a picture; 16-bit colour becomes 8-bit.
- **What exports:** layers, folders, masks, clipping, blend modes, opacity, text (as pixels with its
  text, so Photoshop can set it again when you choose Update), the adjustments Photoshop has (all of
  Herald's own among them, a Color Lookup with its table), layer effects, and the flattened image. Grain, Gaussian Blur, Motion Blur and Add Noise are filters in
  Photoshop, not adjustment layers, so they show only in the flattened image. Shapes become pixels,
  and turned, flipped or scaled layers are drawn into the document's pixel grid with their masks
  applied. Files past 30,000 pixels a side are written as PSB.
- **Size:** files up to 2 GB, images up to Herald Canvas's own limits.

## Linux notes

- **Converting HEIC, TIFF and RAW.** Herald OS Linux ships libheif's tools and ImageMagick. HEIF and
  AVIF stills, TIFF and camera RAW files open. HEIC photos from phones are compressed with HEVC,
  which Fedora's libheif cannot decode: install `libheif-freeworld` from RPM Fusion for those, or
  export them as JPEG first. On other distributions install `libheif-tools` or `libheif-examples`
  (with `libheif-plugin-libde265` for HEVC), and ImageMagick or libvips; when nothing can convert a
  file, the message says which packages to install.
- **Without a graphics chip Herald Canvas knows.** In a virtual machine, or with a graphics driver
  Chromium does not trust, Herald turns on SwiftShader, Chromium's software renderer, so the editor
  still draws. Herald Canvas notices and draws less while things move: a half-resolution draft
  while you paint, drag or move a slider, the full frame once you stop, 8-bit blending, and layer
  thumbnails that update less often. In the Herald OS virtual machine a 3,000 × 2,000 image with
  seven layers paints at about 15 frames a second and pans and zooms at about 40.

## Troubleshooting

- **"Herald Canvas needs WebGL2, which this system does not provide."** The graphics stack offers
  no WebGL at all. On a Mac, check that the GPU is not disabled for Herald OS. On Linux, Herald falls
  back to SwiftShader; if this still appears, `~/.local/state/herald-os/shell.log` says why.
- **It is slow in a virtual machine.** That is the software renderer. A smaller window, a lower zoom
  or fewer adjustment layers and blurs over the area you work on all help; the full-quality frame
  comes a moment after you stop.
- **An image does not open on Linux.** Read the message: it names the packages to install. HEIC
  photos need the HEVC decoder described above.
- **A Photoshop text layer came in as a picture.** Its font is not on this computer (or it is turned
  or warped). Install the font and open the file again, or retype the text.
- **A project changed on disk while I had unsaved edits.** Choose Keep mine (saved over theirs) or
  Load theirs (your edits stay a step behind it, so `Cmd+Z` brings them back).
- **A model download stopped.** Edit > AI Models resumes it, or removes what was downloaded.
- **Hermes cannot find my project.** Save it first: commands work on saved projects, or on the image
  in front.
