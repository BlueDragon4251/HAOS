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
| Crop | `C` | Crops the canvas (`Enter` crops, `Esc` cancels); layers keep their pixels |
| Eyedropper | `I` | Picks a colour from the image |
| Spot Healing Brush | `J` | Paints over a blemish and fills it from around it |
| Brush | `B` | Paints, on the pixels or on the layer's mask |
| Eraser | `E` | Erases (on a mask, hides) |
| Paint Bucket and Gradient | `G` | Fills similar colours, or drags a gradient |
| Type | `T` | Click for a line of text, drag a box for a paragraph; click a text layer to edit it |
| Shape | `U` | Draws a rectangle, rounded rectangle, ellipse or line (`Shift` squares it) |
| Hand | `H` (or hold `Space`) | Moves the view |
| Zoom | `Z` | Zooms in (`Alt` out) |

Other keys: `X` swaps the foreground and background colours and `D` resets them; `[` and `]` change
the brush size, with `Shift` its hardness; the number keys set opacity (`5` is 50%, `4` then `5`
quickly is 45%); the arrow keys nudge the picked layers with the Move tool (`Shift` for 10 pixels).

| Command | macOS | Herald OS Linux |
| --- | --- | --- |
| New, Open, Save, Save As | `Cmd+N`, `Cmd+O`, `Cmd+S`, `Cmd+Shift+S` | `Ctrl` with the same keys |
| Undo, Redo | `Cmd+Z`, `Cmd+Shift+Z` | `Ctrl+Z`, `Ctrl+Shift+Z` |
| Cut, Copy, Copy Merged, Paste | `Cmd+X`, `Cmd+C`, `Cmd+Shift+C`, `Cmd+V` | `Ctrl` with the same keys |
| Fill, with the foreground or background colour | `Shift+F5`, `Alt+Backspace`, `Cmd+Backspace` | `Shift+F5`, `Alt+Backspace`, `Ctrl+Backspace` |
| Free Transform | `Cmd+T` | `Ctrl+T` |
| Select All, Deselect, Reselect, Inverse | `Cmd+A`, `Cmd+D`, `Cmd+Shift+D`, `Cmd+Shift+I` | `Ctrl` with the same keys |
| Feather the selection | `Shift+F6` | `Shift+F6` |
| New Layer, Duplicate (or Layer via Copy), Layer via Cut | `Cmd+Shift+N`, `Cmd+J`, `Cmd+Shift+J` | `Ctrl` with the same keys |
| Group, Ungroup, Clipping Mask | `Cmd+G`, `Cmd+Shift+G`, `Cmd+Alt+G` | `Ctrl` with the same keys |
| Bring Forward, Send Backward (to the front or back with `Shift`) | `Cmd+]`, `Cmd+[` | `Ctrl+]`, `Ctrl+[` |
| Merge Down | `Cmd+E` | `Ctrl+E` |
| Image Size, Canvas Size | `Cmd+Alt+I`, `Cmd+Alt+C` | `Ctrl+Alt+I`, `Ctrl+Alt+C` |
| Zoom in, out, fit, actual pixels | `Cmd+=`, `Cmd+-`, `Cmd+0`, `Cmd+1` | `Ctrl` with the same keys |
| Export as PNG | `Cmd+Alt+Shift+W` | `Ctrl+Alt+Shift+W` |

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
- **Adjustment layers.** Layer > New Adjustment Layer: Hue/Saturation, Levels, Curves, Exposure,
  Gradient Map, Grain, Invert, Black & White, Color Balance, Gaussian Blur, Motion Blur and Add
  Noise. They change everything under them (only the layer below when clipped) and stay editable in
  the Properties panel.
- **Layer effects.** Layer > Layer Effects: stroke, drop shadow, inner shadow, outer glow, inner
  glow and colour overlay, on pictures, text and shapes. Their settings are in the Properties panel.
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
- "Remove the background of the product shot", "take the wire out of the sky" (content-aware fill).
- "Export it as a PSD for the printer" or "as a JPEG at half size".

Hermes works through its `canvas` tool, the same commands the command bar and voice reach: new and
open, layers, text, shapes, adjustments, effects, masks, resizing and cropping, previews, exports,
and the on-device tools. Each change lands in the open window as you watch, as one step: `Cmd+Z`
undoes it, or ask Hermes to undo. On Herald OS Linux, `herald-os canvas` does the same from a
terminal (`herald-os canvas new Poster 1080x1350`, `herald-os canvas text "Night market"`,
`herald-os canvas export ~/Desktop/poster.png`, `herald-os canvas undo`). Hermes never downloads a
model: when one is missing it asks you to allow it in the window.

## Compositor compatibility

Herald Canvas reads and writes the `.comp` format (version 11), so a project moves between Herald
Canvas on Linux or a Mac and Compositor on a Mac. Herald holds every value to
the ranges Compositor accepts (it refuses a whole project over one value outside them) and says
which field is wrong when a change would leave a range. Fields it does not use, such as
Compositor's own settings, are kept as they were. Text keeps Compositor's per-letter colour and
font runs: Herald Canvas draws them and keeps them through edits where the edited range allows
(typed letters take the colour of the letter before them). Compositor's Hue/Saturation settings for
single colour ranges are kept in the file, but Herald Canvas draws only the master setting.

## Photoshop documents

Herald Canvas reads and writes PSD and PSB files itself (with the ag-psd library, in the
background), and lists anything it approximated once the file is open or written.

- **What opens:** pixel layers with their position, opacity, visibility and blend mode; folders;
  layer and folder masks; clipping; text layers (Photoshop's pixels, and the text, font, size,
  colour, alignment, tracking, leading and colour and font runs, so they can be edited); and the
  layer effects Herald draws (drop and inner shadow, outer and inner glow, colour overlay, stroke).
  Adjustment layers open as Hue/Saturation, Levels, Curves, Exposure, Invert, Black & White, Color
  Balance and Gradient Map.
- **What changes:** blend modes Herald lacks (Dissolve, Darker Color, Lighter Color) become Normal; a
  folder's own blend mode becomes Pass Through; other adjustment layers (Brightness/Contrast,
  Vibrance, Photo Filter, Channel Mixer, Color Lookup, Posterize, Threshold, Selective Color) and
  effects (bevel and emboss, satin, gradient and pattern overlays) are left out; smart objects,
  shape layers and vector masks become pixels (vector masks only where Photoshop stored them as a
  mask too); gradient maps keep their first and last colours; text that is turned, warped, vertical
  or set in a font this computer lacks stays a picture; 16-bit colour becomes 8-bit.
- **What exports:** layers, folders, masks, clipping, blend modes, opacity, text (as pixels with its
  text, so Photoshop can set it again when you choose Update), the adjustments Photoshop has, layer
  effects, and the flattened image. Grain, Gaussian Blur, Motion Blur and Add Noise are filters in
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
