import { describe, expect, it } from 'vitest'
import { defaultTransform, type Vec2 } from '../../../../shared/canvas/comp-format.ts'
import { anchorOffset, cropCanvas, flipCanvas, resizeCanvas, rotateCanvas, rotateRaster, scaleImage, trimRect } from './canvas-size.ts'
import { type DocState, pixelLayer } from './document.ts'
import { apply, unitToDocument } from './geometry.ts'
import { Raster } from './raster.ts'

const state = (): DocState => {
  const layer = pixelLayer('Photo', Raster.filled(40, 20, [255, 0, 0, 255]), defaultTransform(40, 20, 10, 10))
  const selection = new Raster(100, 50, 1)
  selection.data[10 * 100 + 10] = 255

  return {
    width: 100,
    height: 50,
    resolution: 72,
    layers: [{ ...layer, mask: Raster.filled(40, 20, 128, 1) }],
    activeLayerId: layer.id,
    guides: [
      { id: 'A', axis: 'vertical', position: 30 },
      { id: 'B', axis: 'horizontal', position: 5 }
    ],
    selection
  }
}

const corner = (s: DocState, unit: Vec2): Vec2 => apply(unitToDocument(s.layers[0].transform), unit).map((value) => Math.round(value * 1000) / 1000) as Vec2

describe('canvas size', () => {
  it('grows around an anchor', () => {
    expect(anchorOffset({ width: 100, height: 50 }, { width: 200, height: 150 }, 'center')).toEqual([50, 50])
    expect(anchorOffset({ width: 100, height: 50 }, { width: 200, height: 150 }, 'top-left')).toEqual([0, 0])
    expect(anchorOffset({ width: 100, height: 50 }, { width: 60, height: 50 }, 'bottom-right')).toEqual([-40, 0])
  })

  it('moves layers, guides and the selection, keeping the pixels', () => {
    const before = state()
    const after = resizeCanvas(before, 200, 150, [50, 50])
    expect(after.layers[0].transform.origin).toEqual([60, 60])
    expect(after.layers[0].pixels).toBe(before.layers[0].pixels)
    expect(after.guides.map((guide) => guide.position)).toEqual([80, 55])
    expect(after.selection!.width).toBe(200)
    expect(after.selection!.data[60 * 200 + 60]).toBe(255)
  })

  it('crops to a box, dropping a selection left outside', () => {
    const after = cropCanvas(state(), { x: 20, y: 15, width: 50, height: 30 })
    expect([after.width, after.height]).toEqual([50, 30])
    expect(after.layers[0].transform.origin).toEqual([-10, -5])
    expect(after.selection).toBeNull()
  })
})

describe('image size', () => {
  it('scales placements and guides, and resamples pixels only when asked', () => {
    const kept = scaleImage(state(), 200, 100, false)
    expect(kept.layers[0].transform).toMatchObject({ origin: [20, 20], size: [80, 40] })
    expect(kept.layers[0].pixels!.width).toBe(40)
    expect(kept.guides.map((guide) => guide.position)).toEqual([60, 10])
    expect(kept.selection!.width).toBe(200)
    const resampled = scaleImage(state(), 50, 25, true)
    expect(resampled.layers[0].pixels!.width).toBe(20)
    expect(resampled.layers[0].mask!.width).toBe(20)
    expect(resampled.layers[0].transform.size).toEqual([20, 10])
  })
})

describe('rotate and flip canvas', () => {
  it('turns a quarter turn clockwise', () => {
    const before = state()
    const after = rotateCanvas(before, 1)
    expect([after.width, after.height]).toEqual([50, 100])
    // The layer's top-left corner (10, 10) goes to (height - 10, 10).
    expect(corner(after, [0, 0])).toEqual([40, 10])
    expect(after.layers[0].transform.rotation).toBe(90)
    expect(after.guides).toEqual([
      { id: 'A', axis: 'horizontal', position: 30 },
      { id: 'B', axis: 'vertical', position: 45 }
    ])
    expect(after.selection!.data[10 * 50 + 39]).toBe(255)
  })

  it('turns back and half way', () => {
    const back = rotateCanvas(state(), 3)
    expect(corner(back, [0, 0])).toEqual([10, 90])
    const half = rotateCanvas(state(), 2)
    expect(corner(half, [0, 0])).toEqual([90, 40])
    expect(rotateCanvas(rotateCanvas(state(), 1), 3).layers[0].transform).toMatchObject({ origin: [10, 10], size: [40, 20] })
  })

  it('mirrors with flips, not a turn', () => {
    const across = flipCanvas(state(), true)
    expect(across.layers[0].transform).toMatchObject({ flipX: true, flipY: false })
    expect(corner(across, [0, 0])).toEqual([90, 10])
    expect(across.guides[0].position).toBe(70)
    const down = flipCanvas(state(), false)
    expect(down.layers[0].transform).toMatchObject({ flipX: false, flipY: true })
    expect(corner(down, [0, 0])).toEqual([10, 40])
  })

  it('rotates rasters', () => {
    const raster = new Raster(3, 2, 1)
    raster.data.set([1, 2, 3, 4, 5, 6])
    expect([...rotateRaster(raster, 1).data]).toEqual([4, 1, 5, 2, 6, 3])
    expect([...rotateRaster(raster, 2).data]).toEqual([6, 5, 4, 3, 2, 1])
    expect([...rotateRaster(raster, 3).data]).toEqual([3, 6, 2, 5, 1, 4])
  })
})

describe('trim', () => {
  it('cuts transparent edges, or edges the colour of the top-left pixel', () => {
    const raster = Raster.filled(10, 10, [255, 255, 255, 255])
    raster.data.set([0, 0, 0, 255], (4 * 10 + 3) * 4)
    raster.data.set([0, 0, 0, 255], (6 * 10 + 7) * 4)
    expect(trimRect(raster, 'top-left')).toEqual({ x: 3, y: 4, width: 5, height: 3 })
    const clear = new Raster(10, 10)
    clear.data.set([1, 1, 1, 9], (2 * 10 + 2) * 4)
    expect(trimRect(clear, 'transparent')).toEqual({ x: 2, y: 2, width: 1, height: 1 })
    expect(trimRect(Raster.filled(4, 4, [5, 5, 5, 255]), 'top-left')).toBeNull()
  })
})
