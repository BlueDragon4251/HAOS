/*
 * What Hermes (and the command bar, voice and the CLI) does in Herald Canvas. A command works on a
 * project: the one it names, or the image in front. When that project is open in this window the
 * change lands in the open document (one undoable step, saved right after); otherwise it is read
 * from disk, changed and written back, and any window showing it reloads.
 */

import { ADJUSTMENT_KINDS, type AdjustmentKind, defaultAdjustment, defaultTransform, LIMITS } from '../../../shared/canvas/comp-format.ts'
import { baseName, CANVAS_IMAGE_EXTENSIONS, isProjectPath, PROJECT_EXTENSION } from '../../../shared/canvas/files.ts'
import { $env } from '../../store/backend.ts'
import { isPanels } from '../../store/shell.ts'
import { blendFrom, describeLayer, describeLayers, fillBox, findByRef, finite, mergeSettings, opacityFrom, placementOf, resolvePath } from './agent-model.ts'
import {
  adjustmentLayer,
  blankLayer,
  type CanvasDocument,
  type CanvasLayer,
  childrenOf,
  type DocState,
  findLayer,
  folderLayer,
  groupLayers,
  insertLayer,
  moveLayer,
  nextName,
  pixelLayer,
  type Placement,
  removeLayers,
  setClipped,
  withLayer
} from './engine/document.ts'
import { documentFromImage, type ExportKind, exportImage, flatten, newDocument, openProject, saveProject, toRaster } from './engine/project.ts'
import { Raster } from './engine/raster.ts'
import { openInCanvas } from './open.ts'

export interface Target {
  doc: CanvasDocument
  /** Open in this window (edits go into it), rather than read from disk for this command. */
  live: boolean
}

const store = () => import('./store.ts')

/** A file's name with its extension, for what Hermes says back. */
const fileName = (file: string): string => file.split('/').pop() || file

// --- Paths and projects ------------------------------------------------------------------------

/** A full path from what Hermes or the person typed (`~/…` works). */
const resolve = (input: string): string => resolvePath(input, $env.get()?.homeDir ?? '')

/** The project in front of the person: the active document of the Canvas window used last. */
export async function currentProject(): Promise<string | null> {
  const windows = await window.heraldOS.canvas.presence()

  for (const entry of windows) {
    const active = entry.documents.find((doc) => doc.key === entry.active) ?? entry.documents[0]

    if (active?.path) {
      return active.path
    }
  }

  return null
}

export async function target(project?: unknown): Promise<Target> {
  const { $documents, activeDocument } = await store()
  const named = typeof project === 'string' && project.trim() ? resolve(project) : null

  if (named) {
    if (!isProjectPath(named)) {
      throw new Error(`${baseName(named)} is not a Herald Canvas project (a folder ending in ${PROJECT_EXTENSION}); open it with canvas.open first`)
    }

    const open = $documents.get().find((doc) => doc.path === named)

    if (open) {
      return { doc: open, live: true }
    }

    if (!(await window.heraldOS.canvas.exists(named))) {
      throw new Error(`There is no project at ${named}`)
    }

    return { doc: await openProject(named), live: false }
  }

  const active = activeDocument()

  if (active) {
    return { doc: active, live: true }
  }

  const current = await currentProject()

  if (current) {
    return target(current)
  }

  throw new Error('No image is open in Herald Canvas: open one (canvas.open) or start one (canvas.new)')
}

/** Record a change as one undoable step, and save it where it lives. */
export async function apply(on: Target, label: string, next: DocState): Promise<void> {
  on.doc.commit(label, next)

  if (!on.doc.path) {
    return
  }

  if (on.live) {
    const { $autosave, save } = await store()

    // The person turned saving off: the change waits in the window like their own edits.
    if ($autosave.get()) {
      await save(on.doc)
    }
  } else {
    await saveProject(on.doc)
  }
}

/** A name for a new project that is not taken yet in a folder ("Poster", "Poster 2", …). */
export async function freeProjectPath(folder: string, name: string): Promise<string> {
  const clean = name.replace(/[/\\:]/g, '-').replace(/\.comp$/i, '').trim() || 'Untitled'

  for (let n = 1; n < 1000; n++) {
    const candidate = `${folder}/${n === 1 ? clean : `${clean} ${n}`}${PROJECT_EXTENSION}`

    if (!(await window.heraldOS.canvas.exists(candidate))) {
      return candidate
    }
  }

  throw new Error(`Too many projects called ${clean} in ${folder}`)
}

// --- Making pixels -----------------------------------------------------------------------------

let colorContext: OffscreenCanvasRenderingContext2D | null = null

/** Any CSS colour ("#ff8800", "tomato", "rgb(10 20 30 / 50%)") as RGBA bytes. */
export function parseColor(input: unknown): [number, number, number, number] {
  const text = String(input ?? '').trim()

  if (!text) {
    throw new Error('Give a colour, like #ff8800 or "tomato"')
  }

  colorContext ??= new OffscreenCanvas(1, 1).getContext('2d', { willReadFrequently: true })!
  colorContext.clearRect(0, 0, 1, 1)
  colorContext.fillStyle = '#010203'
  colorContext.fillStyle = text

  // An unknown colour leaves the marker in place.
  if (colorContext.fillStyle === '#010203' && !/^#?010203$/i.test(text)) {
    throw new Error(`“${text}” is not a colour`)
  }

  colorContext.fillRect(0, 0, 1, 1)
  const [r, g, b, a] = colorContext.getImageData(0, 0, 1, 1).data

  return [r, g, b, a]
}

/** A linear gradient filling a box, at an angle in degrees (0 runs left to right, 90 top to bottom). */
export function gradientRaster(width: number, height: number, stops: string[], angle = 90): Raster {
  if (stops.length < 2) {
    throw new Error('A gradient needs at least two colours, like "#ff0000,#0000ff"')
  }

  const canvas = new OffscreenCanvas(width, height)
  const context = canvas.getContext('2d', { willReadFrequently: true })!
  const r = (angle * Math.PI) / 180
  const half = (Math.abs(width * Math.cos(r)) + Math.abs(height * Math.sin(r))) / 2
  const [cx, cy] = [width / 2, height / 2]
  const gradient = context.createLinearGradient(cx - Math.cos(r) * half, cy - Math.sin(r) * half, cx + Math.cos(r) * half, cy + Math.sin(r) * half)
  stops.forEach((stop, i) => {
    const [cr, cg, cb, ca] = parseColor(stop)
    gradient.addColorStop(i / (stops.length - 1), `rgba(${cr}, ${cg}, ${cb}, ${ca / 255})`)
  })
  context.fillStyle = gradient
  context.fillRect(0, 0, width, height)

  return new Raster(width, height, 4, context.getImageData(0, 0, width, height).data)
}

/** An image for a layer: a file, an http(s) address, or a data: URL. */
export async function loadImage(source: string): Promise<Raster> {
  if (/^https?:\/\//i.test(source)) {
    const fetched = await window.heraldOS.canvas.fetchImage(source)

    return toRaster(fetched.image, 4, fetched.svg)
  }

  if (source.startsWith('data:')) {
    const response = await fetch(source)

    return toRaster(new Uint8Array(await response.arrayBuffer()), 4, source.startsWith('data:image/svg'))
  }

  const file = resolve(source)
  const extension = /(\.[^./]+)$/.exec(file)?.[1]?.toLowerCase() ?? ''

  if (!CANVAS_IMAGE_EXTENSIONS.has(extension)) {
    throw new Error(`Herald Canvas does not read ${extension || 'that kind of file'}`)
  }

  return toRaster(await window.heraldOS.canvas.readImage(file), 4, extension === '.svg')
}

// --- Commands ----------------------------------------------------------------------------------

export interface Outcome {
  summary: string
  data?: Record<string, unknown>
}

/** Where a new layer goes: above a layer, into a folder, or above the active one. */
function placementFrom(state: DocState, args: Record<string, unknown>): Placement {
  if (args.above !== undefined && args.above !== '') {
    return { above: findByRef(state, args.above).id }
  }

  if (args.folder !== undefined && args.folder !== '') {
    const folder = findByRef(state, args.folder)

    if (!folder.isGroup) {
      throw new Error(`${folder.name} is not a folder`)
    }

    return { parentID: folder.id }
  }

  const active = findLayer(state, state.activeLayerId)

  return active ? (active.isGroup ? { parentID: active.id } : { above: active.id }) : {}
}

/** Show a project in Canvas. In this window, wait until it is open, so the next command edits it there. */
async function show(file: string): Promise<void> {
  if (isPanels) {
    openInCanvas(file)

    return
  }

  const { openPath } = await store()
  await openPath(file)
  openInCanvas()
}

/** Show the project (or Canvas itself) to the person. */
export async function open(path: unknown): Promise<Outcome> {
  if (typeof path !== 'string' || !path.trim()) {
    openInCanvas()

    return { summary: 'Opened Herald Canvas' }
  }

  const file = resolve(path)

  if (!(await window.heraldOS.canvas.exists(file))) {
    throw new Error(`Nothing at ${file}`)
  }

  if (isProjectPath(file)) {
    await show(file)

    return { summary: `Opened ${baseName(file)} in Herald Canvas`, data: { path: file } }
  }

  // An image becomes a project beside the others, so edits never touch the original.
  const doc = await documentFromImage(file)
  const project = await freeProjectPath(resolve('~/Pictures/Herald Canvas'), baseName(file))
  await saveProject(doc, project)
  await show(project)

  return { summary: `Opened ${fileName(file)} in Herald Canvas as ${baseName(project)} (the original is untouched)`, data: { path: project, source: file, width: doc.state.width, height: doc.state.height } }
}

export async function create(args: Record<string, unknown>): Promise<Outcome> {
  const width = Math.round(finite(args.width) ?? 1920)
  const height = Math.round(finite(args.height) ?? 1080)

  if (width < 1 || height < 1 || width > LIMITS.side || height > LIMITS.side || width * height > LIMITS.sourcePixels) {
    throw new Error(`A canvas is 1 to ${LIMITS.side.toLocaleString()} pixels a side, ${(LIMITS.sourcePixels / 1e6).toLocaleString()} million in all`)
  }

  const background = (['white', 'black', 'transparent'] as const).find((kind) => kind === args.background) ?? 'white'
  const folder = resolve(typeof args.folder === 'string' && args.folder.trim() ? args.folder : '~/Pictures/Herald Canvas')
  const file = await freeProjectPath(folder, typeof args.name === 'string' ? args.name : 'Untitled')
  const doc = newDocument(width, height, background, Math.round(finite(args.resolution) ?? 72))

  // A colour other than the three plain backgrounds fills the first layer.
  if (typeof args.background === 'string' && !['white', 'black', 'transparent'].includes(args.background)) {
    const layer = pixelLayer('Background', Raster.filled(width, height, parseColor(args.background)))
    doc.state = { ...doc.state, layers: [layer], activeLayerId: layer.id }
  }

  await saveProject(doc, file)
  await show(file)

  return { summary: `Made ${baseName(file)} (${width}×${height}) and opened it`, data: { path: file, width, height } }
}

export async function status(): Promise<Outcome> {
  const windows = await window.heraldOS.canvas.presence()
  const { $documents, activeDocument } = await store()
  // Desktop mode: this window holds the Canvas documents (even while the window is closed), and
  // knows them better than its last report; other windows' reports fill in the rest.
  const documents = $documents.get().map((doc) => ({ key: doc.key, path: doc.path, name: doc.name, width: doc.state.width, height: doc.state.height, modified: doc.modified, layers: doc.state.layers.length, active: doc === activeDocument() }))

  for (const entry of windows) {
    for (const doc of entry.documents) {
      if (!documents.some((known) => known.key === doc.key)) {
        documents.push({ ...doc, active: doc.key === entry.active && !documents.some((known) => known.active) })
      }
    }
  }

  const current = documents.find((doc) => doc.active) ?? documents[0]

  return {
    summary: documents.length ? `${documents.length} image${documents.length === 1 ? '' : 's'} open${current ? `; in front: ${current.name}` : ''}` : 'Nothing is open in Herald Canvas',
    data: { documents: documents.map(({ key: _key, ...doc }) => doc), current: current?.path ?? null }
  }
}

export async function layers(project: unknown): Promise<Outcome> {
  const on = await target(project)
  const { state } = on.doc

  return {
    summary: `${on.doc.name}: ${state.width}×${state.height}, ${state.layers.length} layer${state.layers.length === 1 ? '' : 's'}`,
    data: {
      path: on.doc.path,
      name: on.doc.name,
      width: state.width,
      height: state.height,
      resolution: state.resolution,
      active: findLayer(state, state.activeLayerId)?.name ?? null,
      layers: describeLayers(state)
    }
  }
}

export async function addLayer(args: Record<string, unknown>): Promise<Outcome> {
  const on = await target(args.project)
  const { state } = on.doc
  const canvas = { width: state.width, height: state.height }
  let layer: CanvasLayer

  if (typeof args.source === 'string' && args.source.trim()) {
    const raster = await loadImage(args.source.trim())
    const box = placementOf(raster.width, raster.height, canvas, args)
    const name = typeof args.name === 'string' && args.name.trim() ? args.name.trim() : /^https?:|^data:/.test(args.source) ? nextName(state, 'Image') : baseName(args.source)
    layer = pixelLayer(name, raster, defaultTransform(box.width, box.height, box.x, box.y))
  } else if (typeof args.gradient === 'string' && args.gradient.trim()) {
    const box = fillBox(canvas, args)
    const raster = gradientRaster(box.width, box.height, args.gradient.split(/\s*,\s*/).filter(Boolean), finite(args.angle) ?? 90)
    layer = pixelLayer(typeof args.name === 'string' && args.name.trim() ? args.name.trim() : nextName(state, 'Gradient'), raster, defaultTransform(box.width, box.height, box.x, box.y))
  } else if (args.color !== undefined && args.color !== '') {
    const box = fillBox(canvas, args)
    layer = pixelLayer(typeof args.name === 'string' && args.name.trim() ? args.name.trim() : nextName(state, 'Fill'), Raster.filled(box.width, box.height, parseColor(args.color)), defaultTransform(box.width, box.height, box.x, box.y))
  } else {
    layer = blankLayer(typeof args.name === 'string' && args.name.trim() ? args.name.trim() : nextName(state), state.width, state.height)
  }

  layer = { ...layer, opacity: opacityFrom(args.opacity) ?? 1, blendMode: blendFrom(args.blend) ?? 'Normal' }
  let next = insertLayer(state, layer, placementFrom(state, args))

  if (args.clip === true) {
    next = setClipped(next, layer.id, true)
  }

  await apply(on, 'Add Layer', next)

  return { summary: `Added “${layer.name}” to ${on.doc.name}`, data: { layer: describeLayer(on.doc.state, findLayer(on.doc.state, layer.id)!) } }
}

export async function setLayer(args: Record<string, unknown>): Promise<Outcome> {
  const on = await target(args.project)
  const layer = findByRef(on.doc.state, args.layer)
  const patch: Partial<CanvasLayer> = {}
  const changes: string[] = []

  if (typeof args.name === 'string' && args.name.trim()) {
    patch.name = args.name.trim()
    changes.push('renamed')
  }

  if (typeof args.visible === 'boolean') {
    patch.isVisible = args.visible
    changes.push(args.visible ? 'shown' : 'hidden')
  }

  const opacity = opacityFrom(args.opacity)

  if (opacity !== undefined) {
    patch.opacity = opacity
    changes.push(`opacity ${Math.round(opacity * 100)}%`)
  }

  const blend = blendFrom(args.blend)

  if (blend && !layer.isGroup) {
    patch.blendMode = blend
    changes.push(blend)
  }

  const transform = { ...layer.transform }
  const [x, y, width, height, rotation] = [finite(args.x), finite(args.y), finite(args.width), finite(args.height), finite(args.rotation)]

  if (x !== undefined || y !== undefined || width !== undefined || height !== undefined || rotation !== undefined || typeof args.flipX === 'boolean' || typeof args.flipY === 'boolean') {
    // A size given on one side keeps the proportions.
    const ratio = transform.size[0] / Math.max(1e-6, transform.size[1])
    const newWidth = width ?? (height !== undefined ? height * ratio : transform.size[0])
    const newHeight = height ?? (width !== undefined ? width / ratio : transform.size[1])
    transform.origin = [x ?? transform.origin[0], y ?? transform.origin[1]]
    transform.size = [Math.max(0.01, newWidth), Math.max(0.01, newHeight)]
    transform.rotation = rotation ?? transform.rotation
    transform.flipX = typeof args.flipX === 'boolean' ? args.flipX : transform.flipX
    transform.flipY = typeof args.flipY === 'boolean' ? args.flipY : transform.flipY
    patch.transform = transform
    changes.push('placed')
  }

  let next = Object.keys(patch).length ? withLayer(on.doc.state, layer.id, patch) : on.doc.state

  if (typeof args.clip === 'boolean') {
    next = setClipped(next, layer.id, args.clip)
    changes.push(args.clip ? 'clipped to the layer below' : 'unclipped')
  }

  if (typeof args.order === 'string' && args.order) {
    const current = findLayer(next, layer.id)!
    const siblings = childrenOf(next, current.parentID)
    const index = siblings.indexOf(current)
    const to = { up: index + 1, down: index - 1, top: siblings.length - 1, bottom: 0 }[args.order]

    if (to === undefined) {
      throw new Error('order is up, down, top or bottom')
    }

    next = moveLayer(next, layer.id, current.parentID, Math.max(0, Math.min(siblings.length - 1, to)))
    changes.push(`moved ${args.order}`)
  }

  if (typeof args.folder === 'string' && args.folder) {
    const into = args.folder.toLowerCase() === 'none' || args.folder.toLowerCase() === 'root' ? undefined : findByRef(next, args.folder)

    if (into && !into.isGroup) {
      throw new Error(`${into.name} is not a folder`)
    }

    next = moveLayer(next, layer.id, into?.id, childrenOf(next, into?.id).filter((entry) => entry.id !== layer.id).length)
    changes.push(into ? `into ${into.name}` : 'out of its folder')
  }

  if (!changes.length) {
    throw new Error('Nothing to change: give name, visible, opacity, blend, x, y, width, height, rotation, flipX, flipY, clip, order or folder')
  }

  await apply(on, 'Layer Change', next)

  return { summary: `${layer.name}: ${changes.join(', ')}`, data: { layer: describeLayer(on.doc.state, findLayer(on.doc.state, layer.id)!) } }
}

export async function removeLayer(args: Record<string, unknown>): Promise<Outcome> {
  const on = await target(args.project)
  const layer = findByRef(on.doc.state, args.layer)
  await apply(on, 'Delete Layer', removeLayers(on.doc.state, [layer.id]))

  return { summary: `Removed “${layer.name}”${layer.isGroup ? ' and what was in it' : ''}` }
}

export async function group(args: Record<string, unknown>): Promise<Outcome> {
  const on = await target(args.project)
  const { state } = on.doc
  const refs = String(args.layers ?? '')
    .split(',')
    .map((ref) => ref.trim())
    .filter(Boolean)
  const folder = folderLayer(typeof args.name === 'string' && args.name.trim() ? args.name.trim() : nextName(state, 'Folder'), state.width, state.height)
  const next = refs.length ? groupLayers(state, refs.map((ref) => findByRef(state, ref).id), folder) : insertLayer(state, folder, placementFrom(state, args))
  await apply(on, refs.length ? 'Group Layers' : 'New Folder', next)

  return { summary: refs.length ? `Put ${refs.length} layer${refs.length === 1 ? '' : 's'} in “${folder.name}”` : `Added the folder “${folder.name}”`, data: { folder: folder.id } }
}

export async function addAdjustment(args: Record<string, unknown>): Promise<Outcome> {
  const on = await target(args.project)
  const { state } = on.doc
  const kind = ADJUSTMENT_KINDS.find((entry) => entry.toLowerCase() === String(args.kind ?? '').toLowerCase())

  if (!kind) {
    throw new Error(`Adjustments: ${ADJUSTMENT_KINDS.join(', ')}`)
  }

  let settings: Record<string, unknown> = {}

  if (typeof args.settings === 'string' && args.settings.trim()) {
    try {
      settings = JSON.parse(args.settings) as Record<string, unknown>
    } catch {
      throw new Error('settings must be a JSON object, like {"saturation": 20}')
    }
  }

  const layer: CanvasLayer = {
    ...adjustmentLayer(kind as AdjustmentKind, state.width, state.height),
    ...(typeof args.name === 'string' && args.name.trim() ? { name: args.name.trim() } : {}),
    adjustment: { ...(mergeSettings(defaultAdjustment(kind as AdjustmentKind), settings) as ReturnType<typeof defaultAdjustment>), kind: kind as AdjustmentKind },
    opacity: opacityFrom(args.opacity) ?? 1,
    blendMode: blendFrom(args.blend) ?? 'Normal'
  }
  let next = insertLayer(state, layer, placementFrom(state, args))

  if (args.clip === true) {
    next = setClipped(next, layer.id, true)
  }

  await apply(on, `${kind} Layer`, next)

  return { summary: `Added a ${kind} adjustment${args.clip === true ? ' clipped to the layer below' : ''}`, data: { layer: describeLayer(on.doc.state, findLayer(on.doc.state, layer.id)!) } }
}

const exportKind = (file: string, format: unknown): ExportKind => {
  const named = String(format ?? '').toLowerCase()

  if (named === 'png' || named === 'jpeg' || named === 'webp') {
    return named
  }

  if (named === 'jpg') {
    return 'jpeg'
  }

  return /\.jpe?g$/i.test(file) ? 'jpeg' : /\.webp$/i.test(file) ? 'webp' : 'png'
}

export async function exportTo(args: Record<string, unknown>): Promise<Outcome> {
  const on = await target(args.project)

  if (typeof args.to !== 'string' || !args.to.trim()) {
    throw new Error('Say where to write it: to=~/Pictures/poster.png')
  }

  const kind = exportKind(args.to, args.format)
  let file = resolve(args.to)

  if (!/\.(png|jpe?g|webp)$/i.test(file)) {
    file = `${file}.${kind === 'jpeg' ? 'jpg' : kind}`
  }

  if ((await window.heraldOS.canvas.exists(file)) && args.overwrite !== true) {
    throw new Error(`${fileName(file)} already exists: pass overwrite=true to replace it`)
  }

  const scale = finite(args.scale)
  const quality = finite(args.quality)
  const written = await exportImage(on.doc.state, file, kind, { scale: scale && scale > 0 ? Math.min(scale, 4) : 1, quality: quality !== undefined ? Math.max(0.05, Math.min(1, quality > 1 ? quality / 100 : quality)) : undefined })

  return { summary: `Exported ${fileName(written)}`, data: { file: written } }
}

export async function save(args: Record<string, unknown>): Promise<Outcome> {
  const on = await target(args.project)
  const to = typeof args.to === 'string' && args.to.trim() ? resolve(args.to) : null
  const file = to ? (isProjectPath(to) ? to : `${to}${PROJECT_EXTENSION}`) : on.doc.path

  if (!file) {
    throw new Error('This image has never been saved: say where, with to=~/Pictures/Name.comp')
  }

  if (to && file !== on.doc.path && (await window.heraldOS.canvas.exists(file)) && args.overwrite !== true) {
    throw new Error(`${baseName(file)} already exists: pass overwrite=true to replace it`)
  }

  if (on.live) {
    const { save: saveDocument } = await store()
    await saveDocument(on.doc, { to: file })
  } else {
    await saveProject(on.doc, file)
  }

  return { summary: `Saved ${baseName(file)}`, data: { path: file } }
}

const PREVIEW_FOLDER = '/tmp/herald-canvas-previews'

/** A flattened PNG of the image for Hermes to look at, at most `size` pixels on its long side. */
export async function preview(args: Record<string, unknown>): Promise<Outcome> {
  const on = await target(args.project)
  const { state } = on.doc
  const side = Math.max(64, Math.min(4096, Math.round(finite(args.size) ?? 1024)))
  const scale = Math.min(1, side / Math.max(state.width, state.height))
  const raster = flatten(state, scale)
  const name = (on.doc.path ? baseName(on.doc.path) : on.doc.name).replace(/[^\w.-]+/g, '-') || 'canvas'
  const file = await window.heraldOS.canvas.writeFile(`${PREVIEW_FOLDER}/${name}.png`, { width: raster.width, height: raster.height, channels: 4, data: new Uint8Array(raster.data.buffer, raster.data.byteOffset, raster.data.byteLength) })

  return {
    summary: `Preview of ${on.doc.name} (${raster.width}×${raster.height}): ${file}`,
    data: { file, width: raster.width, height: raster.height, canvas: { width: state.width, height: state.height }, layers: state.layers.length }
  }
}

/** Undo or redo in the image in front (it has to be open in a Canvas window). */
export async function step(direction: 'undo' | 'redo', args: Record<string, unknown>): Promise<Outcome> {
  const on = await target(args.project)

  if (!on.live) {
    if (isPanels) {
      // The Canvas window is its own process there: it takes the request as its payload.
      await window.heraldOS.shell.open('window:canvas', { type: 'payload', payload: { command: direction, path: on.doc.path, at: Date.now() } })

      return { summary: `Asked Herald Canvas to ${direction} in ${on.doc.name}` }
    }

    throw new Error('Undo works in the open Canvas window: open the project first')
  }

  const label = direction === 'undo' ? on.doc.undo() : on.doc.redo()

  if (!label) {
    throw new Error(direction === 'undo' ? 'Nothing to undo' : 'Nothing to redo')
  }

  const { $autosave, save: saveDocument } = await store()

  if (on.doc.path && $autosave.get()) {
    await saveDocument(on.doc)
  }

  return { summary: `${direction === 'undo' ? 'Undid' : 'Redid'} ${label}` }
}
