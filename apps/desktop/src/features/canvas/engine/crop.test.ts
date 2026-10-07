import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../../shared/canvas/comp-format.ts'
import { cropPlan } from '../agent-model.ts'
import { rotateLayers } from './canvas-size.ts'
import { fitRatio, holdRatio, largestTurnedBox, ratioBoxFrom, ratioFrom, ratioOf, straightenAngle } from './crop.ts'
import { type DocState, pixelLayer } from './document.ts'
import { apply, unitToDocument } from './geometry.ts'
import { Raster } from './raster.ts'

const canvas = { width: 1200, height: 800 }

describe('crop ratios', () => {
  it('reads the options as width over height, swapped when asked', () => {
    expect(ratioOf({ ratio: 'free', custom: [4, 5], swapped: false }, canvas)).toBeNull()
    expect(ratioOf({ ratio: '16:9', custom: [4, 5], swapped: false }, canvas)).toBeCloseTo(16 / 9)
    expect(ratioOf({ ratio: '16:9', custom: [4, 5], swapped: true }, canvas)).toBeCloseTo(9 / 16)
    expect(ratioOf({ ratio: 'original', custom: [4, 5], swapped: false }, canvas)).toBeCloseTo(1.5)
    expect(ratioOf({ ratio: 'custom', custom: [2, 3], swapped: false }, canvas)).toBeCloseTo(2 / 3)
  })

  it('fits the largest box of a ratio in the middle', () => {
    expect(fitRatio({ x: 0, y: 0, width: 1200, height: 800 }, 1)).toEqual({ x: 200, y: 0, width: 800, height: 800 })
    expect(fitRatio({ x: 0, y: 0, width: 1200, height: 800 }, 16 / 9)).toEqual({ x: 0, y: 63, width: 1200, height: 675 })
  })

  it('holds a dragged box to the ratio, the far corner staying put', () => {
    expect(ratioBoxFrom([100, 100], [300, 150], 1)).toEqual({ x: 100, y: 100, width: 200, height: 200 })
    expect(ratioBoxFrom([100, 100], [40, 20], 2)).toEqual({ x: -60, y: 20, width: 160, height: 80 })
    expect(holdRatio({ x: 0, y: 0, width: 400, height: 100 }, 2, 'se')).toEqual({ x: 0, y: 0, width: 400, height: 200 })
    expect(holdRatio({ x: 0, y: 50, width: 400, height: 100 }, 2, 'ne')).toEqual({ x: 0, y: -50, width: 400, height: 200 })
    expect(holdRatio({ x: 100, y: 0, width: 200, height: 300 }, 1, 's')).toEqual({ x: 50, y: 0, width: 300, height: 300 })
  })

  it('reads ratios however Hermes writes them', () => {
    expect(ratioFrom('4:5', canvas)).toBeCloseTo(0.8)
    expect(ratioFrom('16x9', canvas)).toBeCloseTo(16 / 9)
    expect(ratioFrom('1.5', canvas)).toBe(1.5)
    expect(ratioFrom('square', canvas)).toBe(1)
    expect(ratioFrom('original', canvas)).toBe(1.5)
    expect(ratioFrom(undefined, canvas)).toBeNull()
    expect(() => ratioFrom('tall', canvas)).toThrow(/width:height/)
  })
})

describe('straighten', () => {
  it('turns a line level, from the horizontal or the vertical, whichever way it was drawn', () => {
    expect(straightenAngle([0, 0], [100, 5])).toBeCloseTo(-2.86, 2)
    expect(straightenAngle([100, 5], [0, 0])).toBeCloseTo(-2.86, 2)
    expect(straightenAngle([0, 0], [100, -10])).toBeCloseTo(5.71, 2)
    expect(straightenAngle([0, 0], [3, 100])).toBeCloseTo(1.72, 2)
    expect(straightenAngle([0, 0], [100, 0])).toBe(0)
  })

  it('keeps the largest box the turned canvas fills', () => {
    expect(largestTurnedBox(1200, 800, 0)).toEqual({ x: 0, y: 0, width: 1200, height: 800 })
    const box = largestTurnedBox(1200, 800, 5)
    expect(box.width / box.height).toBeCloseTo(1.5, 2)
    // Every corner of the box, turned back, lies inside the canvas.
    const radians = (-5 * Math.PI) / 180
    const corners = [
      [box.x, box.y],
      [box.x + box.width, box.y],
      [box.x, box.y + box.height],
      [box.x + box.width, box.y + box.height]
    ]

    for (const [x, y] of corners) {
      const dx = x - 600
      const dy = y - 400
      const u = dx * Math.cos(radians) - dy * Math.sin(radians) + 600
      const v = dx * Math.sin(radians) + dy * Math.cos(radians) + 400
      expect(u).toBeGreaterThanOrEqual(-0.01)
      expect(u).toBeLessThanOrEqual(1200.01)
      expect(v).toBeGreaterThanOrEqual(-0.01)
      expect(v).toBeLessThanOrEqual(800.01)
    }

    expect(largestTurnedBox(1200, 800, 5, 1).width).toBe(largestTurnedBox(1200, 800, 5, 1).height)
  })

  it('turns every layer around the canvas centre', () => {
    const layer = pixelLayer('Photo', new Raster(1200, 800), defaultTransform(1200, 800))
    const state: DocState = { ...canvas, resolution: 72, layers: [layer], activeLayerId: layer.id, guides: [], selection: new Raster(1200, 800, 1) }
    const turned = rotateLayers(state, 90)
    const centre = apply(unitToDocument(turned.layers[0].transform), [0.5, 0.5])
    expect(centre[0]).toBeCloseTo(600)
    expect(centre[1]).toBeCloseTo(400)
    expect(turned.layers[0].transform.rotation).toBeCloseTo(90)
    expect(turned.selection).toBeNull()
    expect(rotateLayers(state, 0)).toBe(state)
  })

  it('plans a crop for Hermes: a ratio alone, a ratio over a box, and a turn', () => {
    expect(cropPlan(canvas, { ratio: '1:1' })).toEqual({ box: { x: 200, y: 0, width: 800, height: 800 }, angle: 0 })
    expect(cropPlan(canvas, { x: 0, y: 0, width: 600, ratio: '3:2' }).box).toEqual({ x: 0, y: 200, width: 600, height: 400 })
    const turned = cropPlan(canvas, { angle: -3 })
    expect(turned.angle).toBe(-3)
    expect(turned.box.width).toBeLessThan(1200)
    expect(() => cropPlan(canvas, { angle: 400 })).toThrow(/-180 to 180/)
  })
})
