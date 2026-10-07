import { describe, expect, it } from 'vitest'
import { defaultTransform, type LayerTransform, type Vec2 } from '../../../../shared/canvas/comp-format.ts'
import { apply, decompose, unitToDocument } from './geometry.ts'
import { Raster } from './raster.ts'
import { dragFrame, follow, frameAround, handleCursor, handlePoints, hitFrame, invertProjective, isConvex, project, type Quad, quadOf, squareToQuad, warpRaster } from './transform.ts'

const near = (actual: Vec2, expected: Vec2, digits = 6) => {
  expect(actual[0]).toBeCloseTo(expected[0], digits)
  expect(actual[1]).toBeCloseTo(expected[1], digits)
}

const corners = (t: LayerTransform): Vec2[] => {
  const m = unitToDocument(t)

  return [apply(m, [0, 0]), apply(m, [1, 0]), apply(m, [1, 1]), apply(m, [0, 1])]
}

describe('decompose', () => {
  it('reads a placement back from its matrix, flips included', () => {
    for (const t of [
      defaultTransform(40, 20, 10, 5),
      { ...defaultTransform(40, 20, 10, 5), rotation: 30 },
      { ...defaultTransform(40, 20, 10, 5), rotation: -120, flipX: true },
      { ...defaultTransform(40, 20, 10, 5), rotation: 45, flipY: true },
      { ...defaultTransform(40, 20, 10, 5), rotation: 10, flipX: true, flipY: true }
    ]) {
      const back = decompose(unitToDocument(t), t)
      expect(back.flipX).toBe(t.flipX)
      expect(back.flipY).toBe(t.flipY)
      corners(back).forEach((point, i) => near(point, corners(t)[i], 3))
    }
  })
})

describe('frames', () => {
  const frame = defaultTransform(100, 50, 0, 0)

  it('finds handles, the inside and the turning ring', () => {
    expect(handlePoints(frame).se).toEqual([100, 50])
    expect(hitFrame(frame, [99, 49], 4)).toBe('se')
    expect(hitFrame(frame, [50, 1], 4)).toBe('n')
    expect(hitFrame(frame, [40, 20], 4)).toBe('move')
    expect(hitFrame(frame, [108, 58], 4)).toBe('rotate')
    expect(hitFrame(frame, [300, 300], 4)).toBeNull()
  })

  it('scales from the opposite corner, or keeping proportions, or from the centre', () => {
    const wider = dragFrame(frame, 'se', [100, 50], [150, 60])
    expect(wider.origin).toEqual([0, 0])
    expect(wider.size).toEqual([150, 60])
    const even = dragFrame(frame, 'se', [100, 50], [200, 60], { constrain: true })
    expect(even.size).toEqual([200, 100])
    const centred = dragFrame(frame, 'e', [100, 25], [110, 25], { fromCentre: true })
    expect(centred.origin).toEqual([-10, 0])
    expect(centred.size).toEqual([120, 50])
  })

  it('flips when a handle crosses the other side', () => {
    const flipped = dragFrame(frame, 'e', [100, 25], [-50, 25])
    expect(flipped.flipX).toBe(true)
    expect(flipped.size[0]).toBeCloseTo(50)
    near(corners(flipped)[0], [0, 0])
  })

  it('turns around the centre, in 15° steps with Shift', () => {
    const turned = dragFrame(frame, 'rotate', [110, 25], [50, 85])
    expect(turned.rotation).toBeCloseTo(90)
    near(apply(unitToDocument(turned), [0.5, 0.5]), [50, 25])
    const snapped = dragFrame(frame, 'rotate', [110, 25], [110, 32], { constrain: true })
    expect(snapped.rotation % 15).toBe(0)
  })

  it('moves and carries layers along with the frame', () => {
    const moved = dragFrame(frame, 'move', [10, 10], [30, 40])
    expect(moved.origin).toEqual([20, 30])
    const layer = { ...defaultTransform(10, 10, 20, 20), rotation: 15 }
    const after = follow(layer, frame, dragFrame(frame, 'se', [100, 50], [200, 100]))
    expect(after.size[0]).toBeCloseTo(20)
    near(apply(unitToDocument(after), [0.5, 0.5]), [50, 50], 3)
    expect(after.rotation).toBeCloseTo(15)
  })

  it('goes around several layers and points its cursors the right way', () => {
    expect(frameAround([defaultTransform(10, 10, 0, 0), defaultTransform(10, 10, 30, 40)])).toMatchObject({ origin: [0, 0], size: [40, 50] })
    expect(handleCursor(frame, 'e')).toBe('ew-resize')
    expect(handleCursor({ ...frame, rotation: 90 }, 'e')).toBe('ns-resize')
  })
})

describe('perspective', () => {
  const quad: Quad = [
    [10, 10],
    [90, 0],
    [100, 100],
    [0, 80]
  ]

  it('maps the unit square onto a quad and back', () => {
    const m = squareToQuad(quad)
    near(project(m, 0, 0), [10, 10])
    near(project(m, 1, 0), [90, 0])
    near(project(m, 1, 1), [100, 100])
    near(project(m, 0, 1), [0, 80])
    near(project(invertProjective(m), 100, 100), [1, 1])
  })

  it('knows a twisted quad from a convex one', () => {
    expect(isConvex(quad)).toBe(true)
    expect(isConvex([quad[0], quad[2], quad[1], quad[3]])).toBe(false)
    expect(isConvex(quadOf(defaultTransform(10, 10)))).toBe(true)
  })

  it('warps pixels onto the quad', () => {
    const source = Raster.filled(10, 10, [200, 100, 50, 255])
    const { raster, bounds } = warpRaster(source, quad)
    expect(bounds).toEqual({ x: 0, y: 0, width: 100, height: 100 })
    expect([...raster.data.subarray((50 * 100 + 50) * 4, (50 * 100 + 50) * 4 + 4)]).toEqual([200, 100, 50, 255])
    expect(raster.data[(2 * 100 + 2) * 4 + 3]).toBe(0)
    const preview = warpRaster(source, quad, 0.25)
    expect(preview.raster.width).toBe(25)
  })
})
