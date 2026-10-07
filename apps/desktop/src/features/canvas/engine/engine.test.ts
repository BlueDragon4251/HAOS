import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../../shared/canvas/comp-format.ts'
import {
  blankLayer,
  CanvasDocument,
  childrenOf,
  type DocState,
  duplicateLayers,
  findLayer,
  folderLayer,
  groupLayers,
  insertLayer,
  isShown,
  moveLayer,
  nextName,
  pixelLayer,
  removeLayers,
  setClipped,
  ungroupLayer,
  withLayer
} from './document.ts'
import { apply, boundsOf, containsPoint, unitToDocument } from './geometry.ts'
import { History, PixelEdit } from './history.ts'
import { Raster, resample } from './raster.ts'

const close = (actual: number[], expected: number[]) => actual.forEach((value, i) => expect(value).toBeCloseTo(expected[i], 6))

const emptyState = (width = 100, height = 80): DocState => ({ width, height, resolution: 72, layers: [], activeLayerId: null, guides: [], selection: null })

const names = (state: DocState) => state.layers.map((layer) => layer.name)

describe('geometry', () => {
  it('places the unit square at the origin and size', () => {
    const m = unitToDocument(defaultTransform(40, 20, 10, 5))
    close(apply(m, [0, 0]), [10, 5])
    close(apply(m, [1, 1]), [50, 25])
  })

  it('turns clockwise around the centre', () => {
    const t = { ...defaultTransform(40, 20, 0, 0), rotation: 90 }
    const m = unitToDocument(t)
    // The top-left corner swings to the top-right of the turned box.
    close(apply(m, [0, 0]), [30, -10])
    close(apply(m, [0.5, 0.5]), [20, 10])
    const box = boundsOf(t)
    close([box.x, box.y, box.width, box.height], [10, -10, 20, 40])
  })

  it('flips inside the box', () => {
    const m = unitToDocument({ ...defaultTransform(40, 20, 0, 0), flipX: true })
    close(apply(m, [0, 0]), [40, 0])
    expect(containsPoint({ ...defaultTransform(40, 20, 0, 0), rotation: 45 }, [20, 10])).toBe(true)
    expect(containsPoint(defaultTransform(40, 20, 0, 0), [41, 10])).toBe(false)
  })
})

describe('raster', () => {
  it('logs what changed for each reader', () => {
    const raster = new Raster(64, 64)
    expect(raster.changedSince(-1)).toBeNull()
    const seen = raster.version
    raster.touch({ x: 2, y: 3, width: 4, height: 5 })
    raster.touch({ x: 10, y: 10, width: 2, height: 2 })
    expect(raster.changedSince(seen)).toEqual({ x: 2, y: 3, width: 10, height: 9 })
    expect(raster.changedSince(raster.version)).toEqual({ x: 0, y: 0, width: 0, height: 0 })
  })

  it('crops past its edges with transparency', () => {
    const raster = Raster.filled(4, 4, [255, 0, 0, 255])
    const crop = raster.crop({ x: 2, y: 2, width: 4, height: 4 })
    expect(crop.width).toBe(4)
    expect([...crop.data.subarray(0, 4)]).toEqual([255, 0, 0, 255])
    expect(crop.data[(3 * 4 + 3) * 4 + 3]).toBe(0)
  })

  it('flips and finds its opaque bounds', () => {
    const raster = new Raster(4, 2)
    raster.data.set([1, 2, 3, 255], 0)
    raster.flip(true)
    expect([...raster.data.subarray(12, 16)]).toEqual([1, 2, 3, 255])
    expect(raster.opaqueBounds()).toEqual({ x: 3, y: 0, width: 1, height: 1 })
  })

  it('resamples without dark fringes from transparent pixels', () => {
    const raster = new Raster(2, 1)
    raster.data.set([255, 255, 255, 255, 0, 0, 0, 0])
    const half = resample(raster, 1, 1)
    expect([...half.data]).toEqual([255, 255, 255, 128])
    const double = resample(raster, 4, 2)
    expect(double.width).toBe(4)
    expect(double.data[0]).toBe(255)
  })
})

describe('history', () => {
  it('undoes and redoes the tiles a tool touched', () => {
    const raster = Raster.filled(300, 300, [0, 0, 0, 255])
    const edit = new PixelEdit(raster)
    edit.prepare({ x: 250, y: 250, width: 10, height: 10 })
    raster.data.fill(255, (255 * 300 + 255) * 4, (255 * 300 + 255) * 4 + 4)
    const step = edit.finish('Brush')!
    expect(step.bytes).toBeLessThan(300 * 300 * 4)
    const history = new History()
    history.push(step)
    history.undo()
    expect(raster.data[(255 * 300 + 255) * 4]).toBe(0)
    history.redo()
    expect(raster.data[(255 * 300 + 255) * 4]).toBe(255)
  })

  it('drops the oldest steps past its memory limit', () => {
    const history = new History(1000)
    const noop = () => {}

    for (let i = 0; i < 5; i++) {
      history.push({ label: `Step ${i}`, bytes: 400, undo: noop, redo: noop })
    }

    expect(history.labels).toEqual(['Step 3', 'Step 4'])
  })
})

describe('document', () => {
  const build = () => {
    let state = emptyState()
    const background = pixelLayer('Background', Raster.filled(100, 80, [255, 255, 255, 255]))
    state = insertLayer(state, background)
    const folder = folderLayer('Folder', 100, 80)
    state = insertLayer(state, folder)
    const inside = blankLayer('Inside', 100, 80)
    state = insertLayer(state, inside)
    const top = blankLayer('Top', 100, 80)
    state = insertLayer(state, top, { above: folder.id })

    return { state, background, folder, inside, top }
  }

  it('puts new layers above the active one, or inside an active folder', () => {
    const { state, folder, inside } = build()
    expect(names(state)).toEqual(['Background', 'Folder', 'Inside', 'Top'])
    expect(findLayer(state, inside.id)!.parentID).toBe(folder.id)
    expect(nextName(state)).toBe('Layer 1')
  })

  it('moves layers into and out of folders', () => {
    const { state, folder, top, inside } = build()
    const moved = moveLayer(state, top.id, folder.id, 0)
    expect(names(moved)).toEqual(['Background', 'Folder', 'Top', 'Inside'])
    expect(childrenOf(moved, folder.id).map((layer) => layer.name)).toEqual(['Top', 'Inside'])
    // A folder cannot go inside itself.
    expect(moveLayer(state, folder.id, folder.id, 0)).toBe(state)
    const out = moveLayer(state, inside.id, undefined, 0)
    expect(names(out)).toEqual(['Inside', 'Background', 'Folder', 'Top'])
  })

  it('groups and ungroups keeping the stacking order', () => {
    const { state, background, top } = build()
    const grouped = groupLayers(state, [background.id, top.id], folderLayer('Group', 100, 80))
    expect(names(grouped)).toEqual(['Folder', 'Inside', 'Group', 'Background', 'Top'])
    const groupId = grouped.activeLayerId!
    const ungrouped = ungroupLayer(grouped, groupId)
    expect(names(ungrouped)).toEqual(['Folder', 'Inside', 'Background', 'Top'])
  })

  it('duplicates with new ids and copied pixels', () => {
    const { state, background } = build()
    const { state: next, ids } = duplicateLayers(state, [background.id])
    const copy = findLayer(next, ids[0])!
    expect(copy.name).toBe('Background copy')
    expect(copy.id).not.toBe(background.id)
    expect(copy.pixels).not.toBe(background.pixels)
    expect(names(next)).toEqual(['Background', 'Background copy', 'Folder', 'Inside', 'Top'])
  })

  it('clips to the layer below and joins its stack', () => {
    let { state } = build()
    const base = pixelLayer('Base', new Raster(10, 10))
    state = insertLayer(state, base, {})
    const first = blankLayer('First', 10, 10)
    state = insertLayer(state, first, { above: base.id })
    const second = blankLayer('Second', 10, 10)
    state = insertLayer(state, second, { above: first.id })
    state = setClipped(state, first.id, true)
    state = setClipped(state, second.id, true)
    expect(findLayer(state, second.id)!.maskSourceID).toBe(base.id)
    // Moving a clipped layer out of the stack releases it; removing the base releases the rest.
    const moved = moveLayer(state, second.id, undefined, 0)
    expect(findLayer(moved, second.id)!.maskSourceID).toBeUndefined()
    const removed = removeLayers(state, [base.id])
    expect(findLayer(removed, first.id)!.maskSourceID).toBeUndefined()
  })

  it('hides layers inside hidden folders', () => {
    const { state, folder, inside } = build()
    const hidden = withLayer(state, folder.id, { isVisible: false })
    expect(isShown(hidden, findLayer(hidden, inside.id)!)).toBe(false)
    expect(isShown(state, findLayer(state, inside.id)!)).toBe(true)
  })

  it('tracks modifications through undo and redo', () => {
    const { state, top } = build()
    const doc = new CanvasDocument({ state, name: 'Test' })
    expect(doc.modified).toBe(false)
    doc.commit('Rename', withLayer(doc.state, top.id, { name: 'Renamed' }))
    expect(doc.modified).toBe(true)
    doc.markSaved('digest')
    expect(doc.modified).toBe(false)
    doc.undo()
    expect(doc.layer(top.id)!.name).toBe('Top')
    expect(doc.modified).toBe(true)
    doc.redo()
    expect(doc.modified).toBe(false)
    // Picking a layer is not an edit.
    doc.select(top.id)
    expect(doc.modified).toBe(false)
  })
})
