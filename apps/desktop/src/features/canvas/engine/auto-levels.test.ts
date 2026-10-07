import { describe, expect, it } from 'vitest'
import { autoModeFrom } from '../agent-model.ts'
import { applyTables, levelsTables } from './adjust-math.ts'
import { autoLevels, clipPoints, gammaFor, histogramsOf } from './auto-levels.ts'

/** RGBA pixels from [r, g, b] triples, opaque. */
const picture = (colours: number[][]): Uint8ClampedArray => Uint8ClampedArray.from(colours.flatMap(([r, g, b]) => [r, g, b, 255]))

/** A ramp of `count` steps from `low` to `high` in each channel. */
const ramp = (count: number, channel: (t: number) => [number, number, number]): number[][] => Array.from({ length: count }, (_, i) => channel(i / (count - 1)))

describe('histograms', () => {
  it('counts opaque pixels only', () => {
    const rgba = Uint8ClampedArray.from([10, 20, 30, 255, 200, 200, 200, 10])
    const h = histogramsOf(rgba)
    expect(h.count).toBe(1)
    expect(h.red[10]).toBe(1)
    expect(h.luma[Math.round(0.2126 * 10 + 0.7152 * 20 + 0.0722 * 30)]).toBe(1)
  })

  it('finds where the clipped share of pixels ends at each end', () => {
    const histogram = new Float64Array(256)

    for (let v = 50; v <= 200; v++) {
      histogram[v] = 10
    }

    expect(clipPoints(histogram, 0)).toEqual([50, 200])
    // 1510 pixels: 5% is 75.5, so seven whole values (70 pixels) are passed at each end.
    expect(clipPoints(histogram, 0.05)).toEqual([57, 193])
  })

  it('bends a midtone to a target', () => {
    expect(gammaFor(0.25, 0.5)).toBeCloseTo(2)
    expect(gammaFor(0.5, 0.5)).toBeCloseTo(1)
    expect(gammaFor(0, 0.5)).toBe(1)
  })
})

describe('automatic levels', () => {
  it('Auto Contrast stretches the three channels together', () => {
    const levels = autoLevels(picture(ramp(151, (t) => [50 + t * 150, 60 + t * 130, 70 + t * 110])), 'contrast', 0)!
    expect(levels.ranges[0]).toMatchObject({ black: 50, white: 200, gamma: 1 })
    expect(levels.ranges.slice(1).every((range) => range.black === 0 && range.white === 255)).toBe(true)
  })

  it('Auto Tone stretches each channel on its own', () => {
    const levels = autoLevels(picture(ramp(256, (t) => [30 + t * 190, 60 + t * 120, t * 255])), 'tone', 0)!
    expect(levels.ranges[0]).toMatchObject({ black: 0, white: 255 })
    expect(levels.ranges[1]).toMatchObject({ black: 30, white: 220 })
    expect(levels.ranges[2]).toMatchObject({ black: 60, white: 180 })
    expect(levels.ranges[3]).toMatchObject({ black: 0, white: 255 })
  })

  it('Auto Color takes out a cast in the ends and the midtones', () => {
    // A gray ramp tinted blue: its shadows lifted in blue, its highlights short of white in red.
    const tinted = (t: number): [number, number, number] => [10 + t * 200, 12 + t * 220, 40 + t * 210]
    const levels = autoLevels(picture(ramp(256, tinted)), 'color', 0.01)!
    const tables = levelsTables(levels)
    const dark = applyTables(tinted(0.02).map((v) => v / 255) as [number, number, number], tables)
    const mid = applyTables(tinted(0.5).map((v) => v / 255) as [number, number, number], tables)
    const light = applyTables(tinted(0.98).map((v) => v / 255) as [number, number, number], tables)
    expect(Math.max(...dark)).toBeLessThan(0.04)
    expect(Math.min(...light)).toBeGreaterThan(0.96)
    expect(Math.max(...mid) - Math.min(...mid)).toBeLessThan(0.02)
  })

  it('leaves a flat picture or one that already spans the range alone', () => {
    expect(autoLevels(picture([[128, 128, 128]]), 'contrast')).toBeNull()
    expect(autoLevels(picture(ramp(256, (t) => [t * 255, t * 255, t * 255])), 'tone', 0)).toBeNull()
    expect(autoLevels(new Uint8ClampedArray(8), 'color')).toBeNull()
  })

  it('reads the kind Hermes asks for', () => {
    expect(autoModeFrom(undefined)).toBe('tone')
    expect(autoModeFrom('Auto Contrast')).toBe('contrast')
    expect(autoModeFrom('colour')).toBe('color')
    expect(() => autoModeFrom('sharpness')).toThrow(/tone, contrast or color/)
  })
})
