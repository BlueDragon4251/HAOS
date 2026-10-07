import { ADJUSTMENT_KINDS, BLEND_MODES } from '../../shared/canvas/comp-format.ts'
import { ok, type OsCommand } from '../store/os-commands.ts'

/*
 * Herald Canvas for Hermes, voice, the command bar and `herald-os canvas`. A command works on the
 * `project` it names (a .comp folder) or on the image in front; edits are one undoable step each
 * and the person watches them land. The editor's code loads only when one of these runs.
 */

const canvas = () => import('../features/canvas/agent.ts')

const project = { name: 'project', type: 'string', description: 'The .comp project (full path or ~/…); the image in front when left out' } as const

const placement = [
  { name: 'x', type: 'number', description: 'Left edge in canvas pixels' },
  { name: 'y', type: 'number', description: 'Top edge in canvas pixels' },
  { name: 'width', type: 'number', description: 'Width in canvas pixels (alone, it keeps the proportions)' },
  { name: 'height', type: 'number', description: 'Height in canvas pixels (alone, it keeps the proportions)' }
] as const

/** A box in canvas pixels, where whatever is left out runs to the canvas's edge. */
const box = (what: string) =>
  [
    { name: 'x', type: 'number', description: `Left edge ${what}, in canvas pixels (0)` },
    { name: 'y', type: 'number', description: `Top edge ${what}, in canvas pixels (0)` },
    { name: 'width', type: 'number', description: `Width ${what} (to the right edge when left out)` },
    { name: 'height', type: 'number', description: `Height ${what} (to the bottom when left out)` }
  ] as const

const appearance = [
  { name: 'opacity', type: 'number', description: '0 to 1 (or a percentage)' },
  { name: 'blend', type: 'string', description: `Blend mode: ${BLEND_MODES.join(', ')}` }
] as const

const where = [
  { name: 'above', type: 'string', description: 'Put it right above this layer (id or name)' },
  { name: 'folder', type: 'string', description: 'Put it at the top of this folder (id or name)' },
  { name: 'clip', type: 'boolean', description: 'Clip it to the layer below, so it shows only where that layer has pixels' }
] as const

const done = async (work: Promise<{ summary: string; data?: Record<string, unknown> }>) => {
  const outcome = await work

  return ok(outcome.summary, { data: outcome.data })
}

export const canvasCommands: readonly OsCommand[] = [
  {
    id: 'canvas.open',
    title: 'Open Herald Canvas',
    description: 'Open Herald Canvas, or open a .comp project in it so the person sees it. An image becomes a new project in ~/Pictures/Herald Canvas (the original is never changed); the answer gives the project path to work on.',
    tier: 'act',
    args: [{ name: 'path', type: 'string', description: 'An image or a .comp project (full path or ~/…)' }],
    phrases: ['open herald canvas', 'open canvas', 'open the image editor'],
    run: async ({ path }) => done((await canvas()).open(path))
  },
  {
    id: 'canvas.new',
    title: 'Start a new image',
    description: 'Make a new .comp project (in ~/Pictures/Herald Canvas unless a folder is given; the name is never reused) and open it. Answers with its path, which later commands take as project.',
    tier: 'act',
    args: [
      { name: 'name', type: 'string', description: 'The project name, e.g. "Spring poster"' },
      { name: 'width', type: 'number', description: 'Pixels (1920 when left out)' },
      { name: 'height', type: 'number', description: 'Pixels (1080 when left out)' },
      { name: 'background', type: 'string', description: 'white, black, transparent, or any CSS colour' },
      { name: 'resolution', type: 'number', description: 'Pixels per inch, for print (72 when left out)' },
      { name: 'folder', type: 'string', description: 'Where the project goes' }
    ],
    phrases: ['new canvas', 'new image in canvas'],
    run: async (args) => done((await canvas()).create(args))
  },
  {
    id: 'canvas.status',
    title: 'What is open in Herald Canvas',
    description: 'The images open in Herald Canvas (path, size, unsaved edits) and which one is in front.',
    tier: 'read',
    args: [],
    run: async () => done((await canvas()).status())
  },
  {
    id: 'canvas.layers',
    title: 'List the layers of an image',
    description: 'The canvas size and every layer, top to bottom as the Layers panel shows them: id, name, kind, folder, visibility, opacity, blend mode, placement, clipping, mask and adjustment.',
    tier: 'read',
    args: [project],
    run: async ({ project: path }) => done((await canvas()).layers(path))
  },
  {
    id: 'canvas.addLayer',
    title: 'Add a layer',
    description:
      'Add a layer: a picture (source = a file path or an http(s) URL), a solid colour (color), a linear gradient (gradient = "colour,colour,…" with angle), or an empty layer. A picture fits inside the canvas, centred, unless fit or a box says otherwise.',
    tier: 'act',
    args: [
      project,
      { name: 'source', type: 'string', description: 'An image file or an http(s) address' },
      { name: 'color', type: 'string', description: 'A solid fill, any CSS colour' },
      { name: 'gradient', type: 'string', description: 'Comma-separated colours, first to last' },
      { name: 'angle', type: 'number', description: 'Gradient direction in degrees: 0 left to right, 90 top to bottom' },
      { name: 'fit', type: 'string', description: 'For a picture: contain (inside the canvas, the default), cover (fill it), none (its own size) or stretch' },
      ...placement,
      { name: 'name', type: 'string', description: 'The layer name' },
      ...appearance,
      ...where
    ],
    run: async (args) => done((await canvas()).addLayer(args))
  },
  {
    id: 'canvas.setLayer',
    title: 'Change a layer',
    description:
      'Change a layer: rename, show or hide, opacity, blend mode, position and size (x, y, width, height; one side alone keeps the proportions), rotation in degrees clockwise, flips, clipping to the layer below, its order (up, down, top, bottom) or the folder it is in ("none" takes it out).',
    tier: 'act',
    args: [
      project,
      { name: 'layer', type: 'string', description: 'The layer (id or name)', required: true },
      { name: 'name', type: 'string', description: 'A new name' },
      { name: 'visible', type: 'boolean', description: 'Show or hide it' },
      ...appearance,
      ...placement,
      { name: 'rotation', type: 'number', description: 'Degrees, clockwise, around its centre' },
      { name: 'flipX', type: 'boolean', description: 'Mirror left to right' },
      { name: 'flipY', type: 'boolean', description: 'Mirror top to bottom' },
      { name: 'clip', type: 'boolean', description: 'Clip it to the layer below (false lets go)' },
      { name: 'order', type: 'string', description: 'Move it among its neighbours: up, down, top or bottom' },
      { name: 'folder', type: 'string', description: 'Move it into this folder (id or name), or "none"' }
    ],
    run: async (args) => done((await canvas()).setLayer(args))
  },
  {
    id: 'canvas.addText',
    title: 'Add text',
    description:
      'Add a text layer that stays editable. Point text: x is its left edge (its centre with align=center, its right edge with align=right) and y its top. Give width for a paragraph that wraps inside a box from x. Fonts are installed families, with a style after them if wanted ("Avenir Next Bold", "Georgia Italic"), or PostScript names ("HelveticaNeue-Bold"). size is the font size in pixels. A new line is \\n.',
    tier: 'act',
    args: [
      project,
      { name: 'content', type: 'string', description: 'The words', required: true },
      { name: 'x', type: 'number', description: 'Left edge (or centre or right edge, by align) in canvas pixels' },
      { name: 'y', type: 'number', description: 'Top edge in canvas pixels' },
      { name: 'width', type: 'number', description: 'A paragraph box this wide (the text wraps in it)' },
      { name: 'height', type: 'number', description: 'The paragraph box height (fits the text when left out)' },
      { name: 'font', type: 'string', description: 'Font family and style, e.g. "Helvetica Neue Bold"' },
      { name: 'size', type: 'number', description: 'Font size in pixels (72)' },
      { name: 'color', type: 'string', description: 'Any CSS colour (black)' },
      { name: 'align', type: 'string', description: 'left, center or right' },
      { name: 'tracking', type: 'number', description: 'Extra space between letters, in pixels' },
      { name: 'leading', type: 'number', description: 'Extra space between lines, in pixels' },
      { name: 'name', type: 'string', description: 'The layer name (the text when left out)' },
      ...appearance,
      ...where
    ],
    run: async (args) => done((await canvas()).addText(args))
  },
  {
    id: 'canvas.setText',
    title: 'Change text',
    description: 'Change a text layer’s words or style. It keeps its place, size and rotation; only what is given changes.',
    tier: 'act',
    args: [
      project,
      { name: 'layer', type: 'string', description: 'The text layer (id or name)', required: true },
      { name: 'content', type: 'string', description: 'New words' },
      { name: 'font', type: 'string', description: 'Font family and style, e.g. "Georgia Italic"' },
      { name: 'size', type: 'number', description: 'Font size in pixels' },
      { name: 'color', type: 'string', description: 'Any CSS colour' },
      { name: 'align', type: 'string', description: 'left, center or right' },
      { name: 'tracking', type: 'number', description: 'Extra space between letters, in pixels' },
      { name: 'leading', type: 'number', description: 'Extra space between lines, in pixels' }
    ],
    run: async (args) => done((await canvas()).setText(args))
  },
  {
    id: 'canvas.addShape',
    title: 'Add a shape',
    description:
      'Add a shape layer: a rectangle (radius rounds its corners; kind=rounded picks a radius), an ellipse (a circle when width equals height) or a line from (x, y) to (x + width, y + height), lineWidth thick. A box left out fills the rest of the canvas.',
    tier: 'act',
    args: [
      project,
      { name: 'kind', type: 'string', description: 'rectangle, rounded, ellipse or line', required: true },
      ...box('of the shape'),
      { name: 'color', type: 'string', description: 'Any CSS colour (black)' },
      { name: 'radius', type: 'number', description: 'Corner radius in pixels, for rectangles' },
      { name: 'lineWidth', type: 'number', description: 'Line thickness in pixels (4)' },
      { name: 'name', type: 'string', description: 'The layer name' },
      ...appearance,
      ...where
    ],
    run: async (args) => done((await canvas()).addShape(args))
  },
  {
    id: 'canvas.resize',
    title: 'Resize an image',
    description:
      'Change the canvas size: width and height grow or cut the canvas around anchor (center by default; top-left, top, bottom-right and so on), and layers keep their pixels. To scale everything instead (Image Size), give scale (0.5 is half) or image=true with width and/or height (one side keeps the proportions).',
    tier: 'act',
    args: [
      project,
      { name: 'width', type: 'number', description: 'New width in pixels' },
      { name: 'height', type: 'number', description: 'New height in pixels' },
      { name: 'anchor', type: 'string', description: 'Where the canvas grows or shrinks from: center, top-left, top, top-right, left, right, bottom-left, bottom or bottom-right' },
      { name: 'scale', type: 'number', description: 'Scale everything by this much (Image Size)' },
      { name: 'image', type: 'boolean', description: 'Scale everything to width and height instead of changing the canvas' },
      { name: 'resample', type: 'boolean', description: 'When scaling, recalculate layer pixels too (true); false only stretches them' }
    ],
    run: async (args) => done((await canvas()).resize(args))
  },
  {
    id: 'canvas.crop',
    title: 'Crop an image',
    description: 'Crop the canvas to a box (canvas pixels from the top-left). Layers keep their pixels, so it can be undone without loss.',
    tier: 'act',
    args: [project, ...box('of the box to keep')],
    run: async (args) => done((await canvas()).crop(args))
  },
  {
    id: 'canvas.removeLayer',
    title: 'Remove a layer',
    description: 'Delete a layer (a folder goes with everything in it). It can be undone in the Canvas window.',
    tier: 'act',
    args: [project, { name: 'layer', type: 'string', description: 'The layer (id or name)', required: true }],
    run: async (args) => done((await canvas()).removeLayer(args))
  },
  {
    id: 'canvas.group',
    title: 'Put layers in a folder',
    description: 'Put layers in a new folder where the topmost of them was, or add an empty folder. Folders pass their opacity and mask on to everything inside.',
    tier: 'act',
    args: [project, { name: 'layers', type: 'string', description: 'Comma-separated layer ids or names; none adds an empty folder' }, { name: 'name', type: 'string', description: 'The folder name' }, where[0], where[1]],
    run: async (args) => done((await canvas()).group(args))
  },
  {
    id: 'canvas.addAdjustment',
    title: 'Add an adjustment layer',
    description: `Add an adjustment layer, which changes everything below it (or only the layer below, with clip). Kinds: ${ADJUSTMENT_KINDS.join(', ')}. settings is JSON over the defaults, e.g. {"hue": 10, "saturation": 25} for Hue/Saturation, {"exposureSettings": {"exposure": 0.5}} for Exposure; the herald-canvas skill lists every field.`,
    tier: 'act',
    args: [
      project,
      { name: 'kind', type: 'string', description: 'The adjustment', required: true, enum: ADJUSTMENT_KINDS },
      { name: 'settings', type: 'string', description: 'JSON object of settings' },
      { name: 'name', type: 'string', description: 'The layer name' },
      ...appearance,
      ...where
    ],
    run: async (args) => done((await canvas()).addAdjustment(args))
  },
  {
    id: 'canvas.export',
    title: 'Export an image',
    description: 'Write the flattened image as PNG, JPEG or WebP. An existing file is replaced only with overwrite=true, which asks the person first.',
    tier: 'act',
    args: [
      project,
      { name: 'to', type: 'string', description: 'The file to write (full path or ~/…)', required: true },
      { name: 'format', type: 'string', description: 'png, jpeg or webp (from the file name when left out)' },
      { name: 'quality', type: 'number', description: 'JPEG and WebP quality, 0 to 1 (0.9)' },
      { name: 'scale', type: 'number', description: 'Size relative to the canvas, e.g. 0.5 for half' },
      { name: 'overwrite', type: 'boolean', description: 'Replace an existing file' }
    ],
    run: async (args) => done((await canvas()).exportTo(args))
  },
  {
    id: 'canvas.save',
    title: 'Save an image',
    description: 'Save the image in front (or project) as a .comp project: to its own file, or to a new one with to. Projects save themselves after each edit, so this matters mostly for unsaved images.',
    tier: 'mutate',
    args: [project, { name: 'to', type: 'string', description: 'A new project path (full path or ~/…)' }, { name: 'overwrite', type: 'boolean', description: 'Replace an existing project' }],
    run: async (args) => done((await canvas()).save(args))
  },
  {
    id: 'canvas.preview',
    title: 'Look at an image',
    description: 'Render the image flattened to a PNG (at most size pixels on its long side, 1024 by default) and answer with the file, so you can look at what you made.',
    tier: 'read',
    args: [project, { name: 'size', type: 'number', description: 'Longest side in pixels' }],
    run: async (args) => done((await canvas()).preview(args))
  },
  {
    id: 'canvas.undo',
    title: 'Undo in Herald Canvas',
    description: 'Undo the last change to the image in front (or project), whoever made it.',
    tier: 'act',
    args: [project],
    phrases: ['undo in canvas'],
    run: async (args) => done((await canvas()).step('undo', args))
  },
  {
    id: 'canvas.redo',
    title: 'Redo in Herald Canvas',
    description: 'Redo what was last undone in the image in front (or project).',
    tier: 'act',
    args: [project],
    run: async (args) => done((await canvas()).step('redo', args))
  }
]
