import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../../shared/canvas/comp-format.ts'
import { alignEdgesFrom, alignToFrom, distributeFrom } from '../agent-model.ts'
import { alignOffsets, alignState, automaticTarget, boxAround, contentBounds, distributeOffsets, distributeState } from './align.ts'
import { type DocState, folderLayer, insertLayer, pixelLayer } from './document.ts'
import { Raster } from './raster.ts'

const box = (x: number, y: number, width: number, height: number) => ({ x, y, width, height })

const emptyState = (): DocState => ({ width: 200, height: 100, resolution: 72, layers: [], activeLayerId: null, guides: [], selection: null })

/** A layer of `width`×`height` pixels at (x, y) with an opaque square of `side` at (ox, oy) inside it. */
function marked(name: string, x: number, y: number, width: number, height: number, ox: number, oy: number, side: number) {
  const pixels = new Raster(width, height)

  for (let py = oy; py < oy + side; py++) {
    for (let px = ox; px < ox + side; px++) {
      pixels.data.set([255, 0, 0, 255], (py * width + px) * 4)
    }
  }

  return pixelLayer(name, pixels, defaultTransform(width, height, x, y))
}

describe('align offsets', () => {
  it('puts each edge or centre on the target', () => {
    const boxes = [box(10, 10, 20, 10), box(50, 30, 40, 20)]
    const target = box(0, 0, 200, 100)
    expect(alignOffsets(boxes, 'left', target)).toEqual([
      [-10, 0],
      [-50, 0]
    ])
    expect(alignOffsets(boxes, 'center', target)).toEqual([
      [80, 0],
      [30, 0]
    ])
    expect(alignOffsets(boxes, 'bottom', target)).toEqual([
      [0, 80],
      [0, 50]
    ])
    expect(alignOffsets(boxes, 'middle', boxAround(boxes)!)).toEqual([
      [0, 15],
      [0, -10]
    ])
  })

  it('spreads edges and centres evenly, the outermost two staying put', () => {
    const boxes = [box(0, 0, 10, 10), box(70, 0, 10, 10), box(20, 0, 30, 10)]
    // Centres 5, 75 and 35: the middle one goes to 40.
    expect(distributeOffsets(boxes, 'center')).toEqual([
      [0, 0],
      [0, 0],
      [5, 0]
    ])
    expect(distributeOffsets(boxes.slice(0, 2), 'center')).toEqual([
      [0, 0],
      [0, 0]
    ])
  })

  it('spaces boxes with equal gaps', () => {
    // Span 0 to 100 holds 60 pixels of boxes: two gaps of 20.
    const boxes = [box(0, 0, 20, 5), box(80, 10, 20, 5), box(30, 20, 20, 5)]
    expect(distributeOffsets(boxes, 'horizontal')).toEqual([
      [0, 0],
      [0, 0],
      [10, 0]
    ])
    const tall = [box(0, 0, 5, 10), box(0, 15, 5, 10), box(0, 90, 5, 10)]
    expect(distributeOffsets(tall, 'vertical').map((offset) => offset[1])).toEqual([0, 30, 0])
  })
})

describe('aligning layers', () => {
  it('measures a layer by what it shows, a folder by what is in it', () => {
    const logo = marked('Logo', 0, 0, 200, 100, 150, 60, 20)
    expect(contentBounds({ ...emptyState(), layers: [logo] }, logo)).toEqual(box(150, 60, 20, 20))
    let state = insertLayer(emptyState(), folderLayer('Folder', 200, 100))
    const folder = state.layers[0]
    state = insertLayer(state, marked('A', 10, 10, 10, 10, 0, 0, 10), { parentID: folder.id })
    state = insertLayer(state, marked('B', 40, 50, 10, 10, 0, 0, 10), { parentID: folder.id })
    expect(contentBounds(state, state.layers[0])).toEqual(box(10, 10, 40, 50))
  })

  it('moves a layer so its pixels sit in the corner, a margin in, on whole pixels', () => {
    const logo = marked('Logo', 0, 0, 200, 100, 150, 60, 20)
    const state = { ...emptyState(), layers: [logo] }
    const { state: next, moved } = alignState(state, [logo.id], { edges: ['bottom', 'right'], to: 'canvas', margin: 8 })
    expect(moved).toBe(1)
    expect(next.layers[0].transform.origin).toEqual([22, 12])
    expect(contentBounds(next, next.layers[0])).toEqual(box(172, 72, 20, 20))
  })

  it('aligns layers to each other, carrying a folder with its contents', () => {
    let state = emptyState()
    state = insertLayer(state, marked('Left', 5, 0, 10, 10, 0, 0, 10))
    state = insertLayer(state, folderLayer('Folder', 200, 100))
    const folder = state.layers.at(-1)!
    state = insertLayer(state, marked('Inside', 60, 40, 10, 10, 0, 0, 10), { parentID: folder.id })
    const { state: next } = alignState(state, [state.layers[0].id, folder.id], { edges: ['left'], to: 'layers' })
    expect(next.layers.find((layer) => layer.name === 'Inside')!.transform.origin).toEqual([5, 40])
    expect(() => alignState(state, [state.layers[0].id], { edges: ['left'], to: 'layers' })).toThrow(/two or more/)
    expect(() => alignState(state, [state.layers[0].id], { edges: ['left'], to: 'selection', selection: null })).toThrow(/selected/)
  })

  it('distributes three or more layers in one change', () => {
    let state = emptyState()

    for (const [name, x] of [
      ['A', 0],
      ['B', 30],
      ['C', 90]
    ] as const) {
      state = insertLayer(state, marked(name, x, 0, 10, 10, 0, 0, 10))
    }

    const { state: next } = distributeState(
      state,
      state.layers.map((layer) => layer.id),
      'horizontal'
    )
    expect(next.layers.map((layer) => layer.transform.origin[0])).toEqual([0, 45, 90])
    expect(() => distributeState(state, [state.layers[0].id, state.layers[1].id], 'left')).toThrow(/three or more/)
  })

  it('picks what to align to as photo editors do', () => {
    expect(automaticTarget(1, false)).toBe('canvas')
    expect(automaticTarget(3, false)).toBe('layers')
    expect(automaticTarget(3, true)).toBe('selection')
  })
})

describe('align arguments for Hermes', () => {
  it('reads edges however they are written', () => {
    expect(alignEdgesFrom('left')).toEqual(['left'])
    expect(alignEdgesFrom('bottom right')).toEqual(['right', 'bottom'])
    expect(alignEdgesFrom('center,middle')).toEqual(['center', 'middle'])
    expect(alignEdgesFrom('centre centre')).toEqual(['center', 'middle'])
    expect(alignEdgesFrom('center left')).toEqual(['left', 'middle'])
    expect(() => alignEdgesFrom('diagonal')).toThrow(/diagonal/)
    expect(() => alignEdgesFrom('')).toThrow(/edge is/)
  })

  it('reads what to align to and how to distribute', () => {
    expect(alignToFrom(undefined, 1)).toBe('canvas')
    expect(alignToFrom('', 2)).toBe('layers')
    expect(alignToFrom('Each other', 1)).toBe('layers')
    expect(alignToFrom('selection', 1)).toBe('selection')
    expect(() => alignToFrom('wall', 1)).toThrow(/canvas/)
    expect(distributeFrom('Horizontally')).toBe('horizontal')
    expect(distributeFrom('centre')).toBe('center')
    expect(() => distributeFrom('sideways')).toThrow(/distribute/)
  })
})
