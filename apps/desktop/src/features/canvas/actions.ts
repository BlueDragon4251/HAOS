/*
 * What the menus, shortcuts and panels do to a Herald Canvas document. Each change is one undoable
 * step named the way the History shows it.
 */

import { type BlendMode, defaultTransform } from '../../../shared/canvas/comp-format.ts'
import {
  blankLayer,
  type CanvasDocument,
  type CanvasLayer,
  childrenOf,
  descendantIds,
  type DocState,
  duplicateLayers,
  findLayer,
  folderLayer,
  groupLayers,
  insertLayer,
  moveLayer,
  nextName,
  pixelLayer,
  placementFor,
  removeLayers,
  setClipped,
  ungroupLayer,
  withLayer
} from './engine/document.ts'
import { baseName } from '../../../shared/canvas/files.ts'
import { apply, containsPoint, invert, moved, pixelToDocument } from './engine/geometry.ts'
import { offscreen, toRaster } from './engine/project.ts'
import { Raster } from './engine/raster.ts'

/** An image file as a new layer, centred, shrunk to fit when it is larger than the canvas (pixels kept). */
export async function placeImage(doc: CanvasDocument, file: string): Promise<void> {
  const raster = await toRaster(await window.heraldOS.canvas.readImage(file), 4, /\.svg$/i.test(file))
  const { width, height } = doc.state
  const fit = Math.min(1, width / raster.width, height / raster.height)
  const w = Math.max(1, Math.round(raster.width * fit))
  const h = Math.max(1, Math.round(raster.height * fit))
  const name = baseName(file)
  const layer = pixelLayer(name, raster, defaultTransform(w, h, Math.round((width - w) / 2), Math.round((height - h) / 2)))
  doc.commit('Place Image', insertLayer(doc.state, layer, placementFor(doc.state)))
}

export function addLayer(doc: CanvasDocument): void {
  const { state } = doc
  doc.commit('New Layer', insertLayer(state, blankLayer(nextName(state), state.width, state.height), placementFor(state)))
}

/** An empty folder above the active layer (or inside the active folder). */
export function addFolder(doc: CanvasDocument): void {
  const { state } = doc
  doc.commit('New Folder', insertLayer(state, folderLayer(nextName(state, 'Folder'), state.width, state.height), placementFor(state)))
}

/** Put the picked layers (or the active one) in a new folder. */
export function groupPicked(doc: CanvasDocument): void {
  const picked = doc.picked

  if (!picked.length) {
    return
  }

  const { state } = doc
  doc.selectedIds = []
  doc.commit('Group Layers', groupLayers(state, picked.map((layer) => layer.id), folderLayer(nextName(state, 'Folder'), state.width, state.height)))
}

export function ungroupActive(doc: CanvasDocument): void {
  const active = doc.active

  if (active?.isGroup) {
    doc.commit('Ungroup Layers', ungroupLayer(doc.state, active.id))
  }
}

export function duplicatePicked(doc: CanvasDocument): void {
  const picked = doc.picked

  if (picked.length) {
    const { state, ids } = duplicateLayers(doc.state, picked.map((layer) => layer.id))
    doc.selectedIds = ids.length > 1 ? ids : []
    doc.commit(picked.length > 1 ? 'Duplicate Layers' : 'Duplicate Layer', state)
  }
}

export function deletePicked(doc: CanvasDocument): void {
  const picked = doc.picked

  if (picked.length) {
    doc.selectedIds = []
    doc.commit(picked.length > 1 ? 'Delete Layers' : 'Delete Layer', removeLayers(doc.state, picked.map((layer) => layer.id)))
  }
}

export function setLayer(doc: CanvasDocument, id: string, patch: Partial<CanvasLayer>, label: string): void {
  if (findLayer(doc.state, id)) {
    doc.commit(label, withLayer(doc.state, id, patch))
  }
}

export const toggleVisible = (doc: CanvasDocument, layer: CanvasLayer): void => setLayer(doc, layer.id, { isVisible: !layer.isVisible }, layer.isVisible ? 'Hide Layer' : 'Show Layer')

export const rename = (doc: CanvasDocument, layer: CanvasLayer, name: string): void => {
  const trimmed = name.trim()

  if (trimmed && trimmed !== layer.name) {
    setLayer(doc, layer.id, { name: trimmed }, 'Rename Layer')
  }
}

export const setBlendMode = (doc: CanvasDocument, layer: CanvasLayer, mode: BlendMode): void => {
  // Folders are pass-through: they keep Normal.
  if (!layer.isGroup) {
    setLayer(doc, layer.id, { blendMode: mode }, 'Blending Change')
  }
}

/** A mask showing everything, or hiding everything; a uniform 1×1 mask until something is painted. */
export function addMask(doc: CanvasDocument, hideAll = false): void {
  const active = doc.active

  if (!active || active.mask) {
    return
  }

  doc.commit(hideAll ? 'Add Mask (Hide All)' : 'Add Mask', withLayer(doc.state, active.id, { mask: Raster.filled(1, 1, hideAll ? 0 : 255, 1), maskEnabled: true, maskLinked: true, maskPlacement: undefined }))
}

export function deleteMask(doc: CanvasDocument): void {
  const active = doc.active

  if (active?.mask) {
    doc.commit('Delete Mask', withLayer(doc.state, active.id, { mask: null, maskEnabled: undefined, maskLinked: undefined, maskPlacement: undefined }))
  }
}

export function toggleMask(doc: CanvasDocument): void {
  const active = doc.active

  if (active?.mask) {
    const enabled = active.maskEnabled !== false
    doc.commit(enabled ? 'Disable Mask' : 'Enable Mask', withLayer(doc.state, active.id, { maskEnabled: !enabled }))
  }
}

export function toggleClipping(doc: CanvasDocument): void {
  const active = doc.active

  if (active && !active.isGroup) {
    const next = setClipped(doc.state, active.id, !active.maskSourceID)

    if (next !== doc.state) {
      doc.commit(active.maskSourceID ? 'Release Clipping Mask' : 'Create Clipping Mask', next)
    }
  }
}

/** Move the active layer one step up or down among its siblings. */
export function arrange(doc: CanvasDocument, direction: 'up' | 'down' | 'top' | 'bottom'): void {
  const active = doc.active

  if (!active) {
    return
  }

  const siblings = childrenOf(doc.state, active.parentID)
  const index = siblings.indexOf(active)
  const target = direction === 'up' ? index + 1 : direction === 'down' ? index - 1 : direction === 'top' ? siblings.length - 1 : 0

  if (target !== index && target >= 0 && target < siblings.length) {
    doc.commit(direction === 'up' || direction === 'top' ? 'Bring Forward' : 'Send Backward', moveLayer(doc.state, active.id, active.parentID, target))
  }
}

/** Layers moved by a document offset; a folder moves with everything inside it, and unlinked masks stay put. */
export function movedState(state: DocState, ids: readonly string[], dx: number, dy: number): DocState {
  const moving = new Set<string>()

  for (const id of ids) {
    moving.add(id)
    descendantIds(state, id).forEach((inside) => moving.add(inside))
  }

  return { ...state, layers: state.layers.map((layer) => (moving.has(layer.id) ? { ...layer, transform: moved(layer.transform, dx, dy) } : layer)) }
}

export function nudge(doc: CanvasDocument, dx: number, dy: number): void {
  const picked = doc.picked

  if (picked.length) {
    doc.commit('Nudge', movedState(doc.state, picked.map((layer) => layer.id), dx, dy))
  }
}

/** Pixels trimmed to what is not transparent, with the placement that keeps them where they were. */
function trimmed(raster: Raster): { pixels: Raster; x: number; y: number } | null {
  const bounds = raster.opaqueBounds()

  return bounds ? { pixels: bounds.width === raster.width && bounds.height === raster.height ? raster : raster.crop(bounds), x: bounds.x, y: bounds.y } : null
}

/** Draw some layers into one new pixel layer (document sized, then trimmed). */
function renderInto(doc: CanvasDocument, ids: string[], overrides = new Map<string, Partial<CanvasLayer>>(), isolated = true): { pixels: Raster; x: number; y: number } | null {
  const compositor = offscreen()

  try {
    const rendered = compositor.render(doc.state, { only: new Set(ids), overrides, isolated, includeHidden: false })

    return trimmed(compositor.read(rendered))
  } finally {
    compositor.textures.clear()
  }
}

/** The layer below the active one, when the two can merge. */
export function mergeTarget(doc: CanvasDocument): CanvasLayer | null {
  const active = doc.active

  if (!active || active.isGroup) {
    return null
  }

  const siblings = childrenOf(doc.state, active.parentID)
  const below = siblings[siblings.indexOf(active) - 1]

  return below && !below.isGroup && !below.adjustment ? below : null
}

/** Merge the active layer into the one below; the result keeps the lower layer's name, opacity and mode. */
export function mergeDown(doc: CanvasDocument): void {
  const active = doc.active
  const below = mergeTarget(doc)

  if (!active || !below) {
    return
  }

  const result = renderInto(doc, [below.id, active.id], new Map([[below.id, { opacity: 1, blendMode: 'Normal' as BlendMode, isVisible: true }]]))
  const merged: CanvasLayer = result
    ? { ...pixelLayer(below.name, result.pixels, defaultTransform(result.pixels.width, result.pixels.height, result.x, result.y)), opacity: below.opacity, blendMode: below.blendMode }
    : blankLayer(below.name, doc.state.width, doc.state.height)
  let state = removeLayers(doc.state, [active.id])
  state = insertLayer(state, { ...merged, parentID: below.parentID }, { above: below.id })
  // Layers clipped to the lower layer stay clipped, now to the merged one.
  state = { ...state, layers: state.layers.filter((layer) => layer.id !== below.id).map((layer) => (layer.maskSourceID === below.id ? { ...layer, maskSourceID: merged.id } : layer)) }
  doc.commit('Merge Down', { ...state, activeLayerId: merged.id })
}

/** Everything visible as one layer; hidden layers are dropped. */
export function flattenImage(doc: CanvasDocument): void {
  const { state } = doc
  const compositor = offscreen()
  let raster: Raster

  try {
    raster = compositor.read(compositor.render(state))
  } finally {
    compositor.textures.clear()
  }

  const layer = pixelLayer('Background', raster)
  doc.selectedIds = []
  doc.commit('Flatten Image', { ...state, layers: [layer], activeLayerId: layer.id })
}

/** The topmost shown layer with a visible pixel at a document point (for picking with the Move tool). */
export function layerAt(doc: CanvasDocument, x: number, y: number): CanvasLayer | null {
  const { state } = doc

  for (let i = state.layers.length - 1; i >= 0; i--) {
    const layer = state.layers[i]

    if (layer.isGroup || !layer.pixels || !layer.isVisible || !containsPoint(layer.transform, [x, y])) {
      continue
    }

    const [px, py] = apply(invert(pixelToDocument(layer.transform, layer.pixels.width, layer.pixels.height)), [x, y])
    const ix = Math.floor(px)
    const iy = Math.floor(py)

    if (ix >= 0 && iy >= 0 && ix < layer.pixels.width && iy < layer.pixels.height && layer.pixels.data[(iy * layer.pixels.width + ix) * 4 + 3] > 8) {
      return layer
    }
  }

  return null
}
