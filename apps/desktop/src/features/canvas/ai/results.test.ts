import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../../shared/canvas/comp-format.ts'
import { type DocState, insertLayer, pixelLayer } from '../engine/document.ts'
import { apply, partPlacement, pixelToDocument } from '../engine/geometry.ts'
import { Raster } from '../engine/raster.ts'
import { boxMask, type Filled, fillArea, fillPiece, holeFromMask, withFillInLayer, withFillLayer, writeFill } from './content-fill.ts'
import { cannotSegment, cutOut, withSubject } from './subject.ts'

const empty = (): DocState => ({ width: 200, height: 100, resolution: 72, layers: [], activeLayerId: null, guides: [], selection: null })

/** A 100×50 picture with an opaque square in its middle. */
function photo(): Raster {
  return Raster.filled(100, 50, [200, 100, 50, 255])
}

describe('placing part of a layer', () => {
  it('keeps the part exactly where it was, turned and scaled alike', () => {
    const t = { ...defaultTransform(200, 100, 30, 40), rotation: 30, flipX: true }
    const part = { x: 20, y: 10, width: 40, height: 25 }
    const placed = partPlacement(t, 100, 50, part)
    const whole = pixelToDocument(t, 100, 50)
    const piece = pixelToDocument(placed, part.width, part.height)

    for (const [px, py] of [
      [0, 0],
      [40, 0],
      [40, 25],
      [13, 7]
    ]) {
      const a = apply(piece, [px, py])
      const b = apply(whole, [part.x + px, part.y + py])
      expect(a[0]).toBeCloseTo(b[0], 2)
      expect(a[1]).toBeCloseTo(b[1], 2)
    }
  })
})

describe('what Remove Background makes', () => {
  const mask = () => {
    const out = new Raster(100, 50, 1)

    for (let y = 10; y < 40; y++) {
      out.data.fill(255, y * 100 + 30, y * 100 + 70)
    }

    return out
  }

  it('adds the subject as a linked mask, nothing erased', () => {
    let state = empty()
    const layer = pixelLayer('Photo', photo(), defaultTransform(100, 50, 50, 25))
    state = insertLayer(state, layer, {})
    const next = withSubject(state, layer, mask(), 'mask')
    expect(next.layers[0]).toMatchObject({ maskEnabled: true, maskLinked: true })
    expect(next.layers[0].pixels).toBe(layer.pixels)
    expect(next.layers[0].mask?.data[15 * 100 + 50]).toBe(255)
  })

  it('cuts the subject out onto a trimmed layer in the same place, hiding the original', () => {
    let state = empty()
    const layer = pixelLayer('Photo', photo(), defaultTransform(100, 50, 50, 25))
    state = insertLayer(state, layer, {})
    const next = withSubject(state, layer, mask(), 'cutout')
    expect(next.layers.map((entry) => [entry.name, entry.isVisible])).toEqual([
      ['Photo', false],
      ['Photo cut-out', true]
    ])
    const piece = next.layers[1]
    expect([piece.pixels?.width, piece.pixels?.height]).toEqual([40, 30])
    expect(piece.transform.origin).toEqual([80, 35])
    expect(cutOut(photo(), new Raster(100, 50, 1))).toBeNull()
    expect(cannotSegment(undefined)).toMatch(/Pick a layer/)
    expect(cannotSegment(pixelLayer('Photo', photo()))).toBeNull()
  })
})

describe('content-aware fill around the worker', () => {
  it('maps a document box onto a placed layer as a hole', () => {
    const t = defaultTransform(100, 50, 50, 25)
    const hole = holeFromMask(boxMask(200, 100, { x: 60, y: 30, width: 20, height: 10 }), pixelToDocument(t, 100, 50), 100, 50)!
    expect(hole.bounds).toEqual({ x: 10, y: 5, width: 20, height: 10 })
    expect(holeFromMask(boxMask(200, 100, { x: 0, y: 0, width: 10, height: 10 }), pixelToDocument(t, 100, 50), 100, 50)).toBeNull()
    expect(fillArea(hole, 100, 50, 'around', 8)).toEqual({ x: 2, y: 0, width: 36, height: 23 })
    expect(fillArea(hole, 100, 50, 'all')).toEqual({ x: 0, y: 0, width: 100, height: 50 })
  })

  it('writes only the filled pixels back, in the layer or on a layer of their own', () => {
    const rect = { x: 10, y: 5, width: 4, height: 2 }
    const filled: Filled = { rect, rgba: new Uint8ClampedArray(4 * 2 * 4).fill(9), hole: Uint8Array.from([0, 255, 255, 0, 0, 128, 0, 0]) }
    const pixels = photo()
    writeFill(pixels, filled)
    expect([...pixels.data.subarray((5 * 100 + 10) * 4, (5 * 100 + 12) * 4)]).toEqual([200, 100, 50, 255, 9, 9, 9, 9])
    const piece = fillPiece(filled)
    expect([piece.width, piece.height]).toEqual([4, 2])
    expect(piece.data[3]).toBe(0)
    expect(piece.data[4 * 5 + 3]).toBe(Math.round((9 * 128) / 255))
    let state = empty()
    const layer = pixelLayer('Photo', photo(), defaultTransform(100, 50, 50, 25))
    state = insertLayer(state, layer, {})
    const inLayer = withFillInLayer(state, layer.id, filled)
    expect(inLayer.layers[0].pixels).not.toBe(layer.pixels)
    expect(layer.pixels!.data[(5 * 100 + 11) * 4]).toBe(200)
    const onTop = withFillLayer(state, filled, { transform: layer.transform, width: 100, height: 50 }, layer.id)
    expect(onTop.layers[1].transform.origin).toEqual([60, 30])
    expect(onTop.layers[1].name).toBe('Content-Aware Fill 1')
  })
})
