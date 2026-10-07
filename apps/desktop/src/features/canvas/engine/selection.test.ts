import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../../shared/canvas/comp-format.ts'
import { pixelToDocument } from './geometry.ts'
import { Raster } from './raster.ts'
import { coverageReader, selectionFromRaster, toDocumentPixels } from './sampling.ts'
import {
  combineSelection,
  contractSelection,
  ellipsePoints,
  expandSelection,
  featherSelection,
  invertSelection,
  polygonMask,
  rectPoints,
  selectAll,
  shiftSelection,
  traceOutline
} from './selection.ts'

const at = (raster: Raster, x: number, y: number) => raster.data[y * raster.width + x]
const total = (raster: Raster) => raster.data.reduce((sum, value) => sum + value, 0)

describe('selection shapes', () => {
  it('fills a whole-pixel rectangle exactly', () => {
    const mask = polygonMask(10, 10, rectPoints({ x: 2, y: 3, width: 4, height: 2 }))
    expect(at(mask, 2, 3)).toBe(255)
    expect(at(mask, 5, 4)).toBe(255)
    expect(at(mask, 6, 4)).toBe(0)
    expect(at(mask, 2, 5)).toBe(0)
    expect(total(mask)).toBe(8 * 255)
  })

  it('antialiases edges that fall inside pixels', () => {
    const mask = polygonMask(10, 10, rectPoints({ x: 1.5, y: 1, width: 3, height: 2 }))
    expect(at(mask, 1, 1)).toBe(128)
    expect(at(mask, 2, 1)).toBe(255)
    expect(at(mask, 4, 1)).toBe(128)
  })

  it('draws an ellipse about the area it should have', () => {
    const mask = polygonMask(100, 100, ellipsePoints({ x: 10, y: 20, width: 80, height: 60 }))
    const area = total(mask) / 255
    expect(Math.abs(area - Math.PI * 40 * 30) / (Math.PI * 40 * 30)).toBeLessThan(0.01)
    expect(at(mask, 50, 50)).toBe(255)
    expect(at(mask, 12, 22)).toBe(0)
  })

  it('leaves a hole where a lasso crosses itself', () => {
    // Two overlapping squares traced as one outline: even-odd leaves their overlap out.
    const mask = polygonMask(20, 20, [
      [0, 0],
      [10, 0],
      [10, 10],
      [5, 10],
      [5, 5],
      [15, 5],
      [15, 15],
      [0, 15]
    ])
    expect(at(mask, 2, 2)).toBe(255)
    expect(at(mask, 7, 7)).toBe(0)
    expect(at(mask, 12, 12)).toBe(255)
  })
})

describe('selection modes', () => {
  const a = polygonMask(10, 10, rectPoints({ x: 0, y: 0, width: 6, height: 10 }))
  const b = polygonMask(10, 10, rectPoints({ x: 4, y: 0, width: 6, height: 10 }))

  it('replaces, adds, takes away and intersects', () => {
    expect(combineSelection(a, b, 'new')).toBe(b)
    expect(total(combineSelection(a, b, 'add')!) / 255).toBe(100)
    const left = combineSelection(a, b, 'subtract')!
    expect(at(left, 3, 5)).toBe(255)
    expect(at(left, 4, 5)).toBe(0)
    expect(total(combineSelection(a, b, 'intersect')!) / 255).toBe(20)
  })

  it('knows when nothing is left', () => {
    expect(combineSelection(a, a, 'subtract')).toBeNull()
    expect(combineSelection(null, b, 'subtract')).toBeNull()
    expect(combineSelection(null, b, 'intersect')).toBe(b)
    expect(invertSelection(selectAll(4, 4))).toBeNull()
    expect(total(invertSelection(a)!) / 255).toBe(40)
  })

  it('moves by whole pixels and loses what falls off', () => {
    const moved = shiftSelection(a, 6, 0)!
    expect(at(moved, 6, 0)).toBe(255)
    expect(at(moved, 5, 0)).toBe(0)
    expect(total(moved) / 255).toBe(40)
    expect(shiftSelection(a, 20, 0)).toBeNull()
  })
})

describe('refining', () => {
  const square = polygonMask(40, 40, rectPoints({ x: 10, y: 10, width: 20, height: 20 }))

  it('feathers into a soft edge that keeps the area', () => {
    const soft = featherSelection(square, 6)!
    expect(at(soft, 20, 20)).toBe(255)
    expect(at(soft, 10, 20)).toBeGreaterThan(60)
    expect(at(soft, 10, 20)).toBeLessThan(200)
    expect(Math.abs(total(soft) - total(square)) / total(square)).toBeLessThan(0.02)
    // The canvas edge is extended: everything selected stays selected.
    expect(at(featherSelection(selectAll(20, 20), 8)!, 0, 0)).toBe(255)
  })

  it('expands and contracts by a distance', () => {
    const grown = expandSelection(square, 3)!
    expect(at(grown, 7, 20)).toBe(255)
    expect(at(grown, 6, 20)).toBe(0)
    // Corners grow round.
    expect(at(grown, 7, 7)).toBe(0)
    const shrunk = contractSelection(square, 3)!
    expect(at(shrunk, 13, 20)).toBe(255)
    expect(at(shrunk, 12, 20)).toBe(0)
    expect(contractSelection(square, 15)).toBeNull()
    // The canvas edge is not an edge of the selection.
    expect(at(contractSelection(selectAll(10, 10), 2)!, 0, 0)).toBe(255)
  })
})

describe('outline', () => {
  it('traces a rectangle as one loop of four corners, clockwise', () => {
    const loops = traceOutline(polygonMask(10, 10, rectPoints({ x: 2, y: 3, width: 4, height: 2 })))
    expect(loops).toHaveLength(1)
    expect([...loops[0]]).toEqual([2, 3, 6, 3, 6, 5, 2, 5])
  })

  it('traces holes and pieces that only touch at a corner apart', () => {
    const ring = Raster.filled(5, 5, 255, 1)
    ring.data[2 * 5 + 2] = 0
    expect(traceOutline(ring)).toHaveLength(2)
    const diagonal = new Raster(4, 4, 1)
    diagonal.data[1 * 4 + 1] = 255
    diagonal.data[2 * 4 + 2] = 255
    expect(traceOutline(diagonal)).toHaveLength(2)
  })

  it('coarsens a very busy edge', () => {
    const noise = new Raster(64, 64, 1)
    noise.data.forEach((_, i) => (noise.data[i] = (i * 7919) % 3 === 0 ? 255 : 0))
    const fine = traceOutline(noise).reduce((sum, loop) => sum + loop.length, 0)
    const coarse = traceOutline(noise, 500).reduce((sum, loop) => sum + loop.length, 0)
    expect(coarse).toBeLessThan(fine)
  })
})

describe('sampling', () => {
  it('reads a selection under each pixel of a placed layer', () => {
    const selection = polygonMask(20, 20, rectPoints({ x: 10, y: 0, width: 10, height: 20 }))
    const aligned = coverageReader(selection, pixelToDocument(defaultTransform(10, 10, 5, 5), 10, 10))
    expect(aligned(4, 0)).toBe(0)
    expect(aligned(5, 0)).toBe(255)
    const doubled = coverageReader(selection, pixelToDocument(defaultTransform(20, 20, 0, 0), 10, 10))
    expect(doubled(4, 3)).toBe(0)
    expect(doubled(5, 3)).toBe(255)
    expect(coverageReader(null, pixelToDocument(defaultTransform(1, 1), 1, 1))(0, 0)).toBe(255)
  })

  it('shows a layer in the document and selects its pixels', () => {
    const pixels = Raster.filled(4, 4, [255, 0, 0, 255])
    const toDocument = pixelToDocument(defaultTransform(8, 8, 2, 2), 4, 4)
    const shown = toDocumentPixels(pixels, toDocument, { x: 0, y: 0, width: 12, height: 12 })
    expect(shown.data[(5 * 12 + 5) * 4 + 3]).toBe(255)
    expect(shown.data[(0 * 12 + 0) * 4 + 3]).toBe(0)
    const selection = selectionFromRaster(pixels, toDocument, 12, 12)!
    expect(at(selection, 5, 5)).toBe(255)
    expect(at(selection, 11, 11)).toBe(0)
  })
})
