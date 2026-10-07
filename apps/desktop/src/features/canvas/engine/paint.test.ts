import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../../shared/canvas/comp-format.ts'
import { eraseRaster, fillRaster, gradientPosition, paintGradient, similarPixels } from './fill.ts'
import { pixelToDocument } from './geometry.ts'
import { History } from './history.ts'
import { dabAlpha, DabPlacer, Smoother, Stroke } from './paint.ts'
import { Raster } from './raster.ts'
import { polygonMask, rectPoints } from './selection.ts'

const pixel = (raster: Raster, x: number, y: number) => [...raster.data.subarray((y * raster.width + x) * raster.channels, (y * raster.width + x + 1) * raster.channels)]
const brush = { size: 10, hardness: 1, opacity: 1, flow: 1, spacing: 0.25 }
const identity = (raster: Raster) => pixelToDocument(defaultTransform(raster.width, raster.height), raster.width, raster.height)

describe('dabs', () => {
  it('places dabs at even spacing, carrying the rest over', () => {
    const placer = new DabPlacer(() => 10)
    expect(placer.to(0, 0)).toEqual([{ x: 0, y: 0, pressure: 1 }])
    expect(placer.to(25, 0).map((dab) => dab.x)).toEqual([10, 20])
    expect(placer.to(30, 0).map((dab) => dab.x)).toEqual([30])
    expect(placer.to(30, 0)).toEqual([])
  })

  it('spaces dabs by the pressure where they land', () => {
    const placer = new DabPlacer((pressure) => 10 * pressure)
    placer.to(0, 0, 0.5)
    const dabs = placer.to(20, 0, 0.5)
    expect(dabs.map((dab) => dab.x)).toEqual([5, 10, 15, 20])
  })

  it('has a hard rim and a soft inside', () => {
    expect(dabAlpha(0, 10, 1)).toBe(1)
    expect(dabAlpha(10.5, 10, 1)).toBe(0)
    expect(dabAlpha(10, 10, 1)).toBeCloseTo(0.5)
    expect(dabAlpha(5, 10, 0)).toBeCloseTo(0.5)
    expect(dabAlpha(0, 10, 0)).toBe(1)
  })

  it('smooths a corner into a curve through the midpoints', () => {
    const smoother = new Smoother()
    const points = [...smoother.add({ x: 0, y: 0, pressure: 1 }), ...smoother.add({ x: 10, y: 0, pressure: 1 }), ...smoother.add({ x: 10, y: 10, pressure: 1 }), ...smoother.end()]
    expect(points[0]).toEqual({ x: 0, y: 0, pressure: 1 })
    expect(points.at(-1)).toEqual({ x: 10, y: 10, pressure: 1 })
    // The corner is cut: no point passes through (10, 0).
    expect(points.some((point) => point.x === 10 && point.y === 0)).toBe(false)
  })
})

describe('strokes', () => {
  it('paints a line and undoes it as one step', () => {
    const raster = new Raster(64, 32)
    const stroke = new Stroke(raster, identity(raster), brush, { colour: [255, 0, 0], erase: false }, null)
    stroke.to(5, 16)
    stroke.to(40, 16)
    stroke.end()
    expect(pixel(raster, 20, 16)).toEqual([255, 0, 0, 255])
    expect(pixel(raster, 20, 2)[3]).toBe(0)
    const history = new History()
    history.push(stroke.finish('Brush')!)
    history.undo()
    expect(pixel(raster, 20, 16)[3]).toBe(0)
    history.redo()
    expect(pixel(raster, 20, 16)).toEqual([255, 0, 0, 255])
  })

  it('never goes past its opacity where it crosses itself', () => {
    const raster = new Raster(40, 40)
    const stroke = new Stroke(raster, identity(raster), { ...brush, opacity: 0.5, flow: 0.5 }, { colour: [0, 0, 255], erase: false }, null)

    for (let i = 0; i < 6; i++) {
      stroke.to(5, 20)
      stroke.to(35, 20)
    }

    stroke.end()
    expect(Math.abs(pixel(raster, 20, 20)[3] - 127.5)).toBeLessThanOrEqual(0.5)
  })

  it('stays inside the selection', () => {
    const raster = new Raster(40, 20)
    const selection = polygonMask(40, 20, rectPoints({ x: 0, y: 0, width: 20, height: 20 }))
    const stroke = new Stroke(raster, identity(raster), brush, { colour: [0, 255, 0], erase: false }, selection)
    stroke.to(5, 10)
    stroke.to(35, 10)
    stroke.end()
    expect(pixel(raster, 10, 10)[3]).toBe(255)
    expect(pixel(raster, 30, 10)[3]).toBe(0)
  })

  it('maps document points onto a moved and scaled layer', () => {
    const raster = new Raster(20, 20)
    // The layer is drawn at twice its size, from (100, 100).
    const stroke = new Stroke(raster, pixelToDocument(defaultTransform(40, 40, 100, 100), 20, 20), brush, { colour: [9, 9, 9], erase: false }, null)
    stroke.to(120, 120)
    stroke.end()
    expect(pixel(raster, 10, 10)[3]).toBe(255)
    // A brush ten document pixels across is five raster pixels across.
    expect(pixel(raster, 12, 10)[3]).toBeGreaterThan(0)
    expect(pixel(raster, 14, 10)[3]).toBe(0)
  })

  it('erases alpha and paints gray into masks', () => {
    const raster = Raster.filled(20, 20, [10, 20, 30, 255])
    const erase = new Stroke(raster, identity(raster), brush, { colour: [0, 0, 0], erase: true }, null)
    erase.to(10, 10)
    erase.end()
    expect(pixel(raster, 10, 10)).toEqual([10, 20, 30, 0])
    const mask = Raster.filled(20, 20, 255, 1)
    const hide = new Stroke(mask, identity(mask), brush, { colour: [0, 0, 0], erase: false }, null)
    hide.to(10, 10)
    hide.end()
    expect(pixel(mask, 10, 10)).toEqual([0])
    expect(pixel(mask, 0, 0)).toEqual([255])
  })
})

describe('fills', () => {
  const picture = () => {
    const raster = Raster.filled(10, 10, [255, 255, 255, 255])
    // A black wall down column 5, and a black block at the far right.
    for (let y = 0; y < 10; y++) raster.data.set([0, 0, 0, 255], (y * 10 + 5) * 4)
    raster.data.set([250, 250, 250, 255], (2 * 10 + 2) * 4)
    return raster
  }

  it('finds joined pixels of a colour, within a tolerance', () => {
    const left = similarPixels(picture(), 1, 1, 0, true)!
    expect(left.data[1 * 10 + 1]).toBe(255)
    expect(left.data[2 * 10 + 2]).toBe(0)
    expect(left.data[1 * 10 + 8]).toBe(0)
    const tolerant = similarPixels(picture(), 1, 1, 10, true)!
    expect(tolerant.data[2 * 10 + 2]).toBe(255)
    const everywhere = similarPixels(picture(), 1, 1, 0, false)!
    expect(everywhere.data[1 * 10 + 8]).toBe(255)
    expect(similarPixels(picture(), 20, 1, 0, true)).toBeNull()
  })

  it('treats all transparent pixels alike', () => {
    const raster = new Raster(4, 1)
    raster.data.set([255, 0, 0, 0, 0, 255, 0, 0, 1, 2, 3, 255, 0, 0, 0, 0])
    const found = similarPixels(raster, 0, 0, 0, false)!
    expect([...found.data]).toEqual([255, 255, 0, 255])
  })

  it('fills and erases by strength', () => {
    const raster = Raster.filled(4, 1, [0, 0, 0, 255])
    fillRaster(raster, { x: 0, y: 0, width: 4, height: 1 }, [255, 255, 255, 255], (x) => (x < 2 ? 1 : 0.5))
    expect(pixel(raster, 0, 0)).toEqual([255, 255, 255, 255])
    expect(pixel(raster, 3, 0)).toEqual([128, 128, 128, 255])
    eraseRaster(raster, { x: 0, y: 0, width: 4, height: 1 }, (x) => (x === 0 ? 1 : 0))
    expect(pixel(raster, 0, 0)[3]).toBe(0)
    expect(pixel(raster, 1, 0)[3]).toBe(255)
  })

  it('lays linear and radial gradients', () => {
    const spec = { kind: 'linear' as const, from: [0, 0] as [number, number], to: [100, 0] as [number, number], start: [0, 0, 0, 255] as [number, number, number, number], end: [255, 255, 255, 255] as [number, number, number, number] }
    expect(gradientPosition(spec, 50, 30)).toBeCloseTo(0.5)
    expect(gradientPosition(spec, -10, 0)).toBe(0)
    expect(gradientPosition({ ...spec, kind: 'radial' }, 0, 50)).toBeCloseTo(0.5)
    const raster = new Raster(100, 1)
    paintGradient(raster, { x: 0, y: 0, width: 100, height: 1 }, identity(raster), { ...spec, end: [0, 0, 0, 0] }, () => 1)
    // A fade to transparency keeps its colour as it goes.
    expect(pixel(raster, 0, 0)[3]).toBeGreaterThan(250)
    expect(Math.abs(pixel(raster, 50, 0)[3] - 127)).toBeLessThan(3)
    expect(pixel(raster, 50, 0).slice(0, 3)).toEqual([0, 0, 0])
  })
})
