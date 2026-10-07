import { describe, expect, it } from 'vitest'
import { filterKindFrom } from '../agent-model.ts'
import { applyFilter, checkFilter, filterReach, type FilterSpec, gaussianPlane, medianChannel, motionPlane, type Pixels, scaledFilter } from './filters.ts'

/** Opaque RGBA pixels from a gray value per pixel. */
const grayPixels = (width: number, height: number, value: (x: number, y: number) => number): Pixels => {
  const data = new Uint8ClampedArray(width * height * 4)

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const v = value(x, y)
      data.set([v, v, v, 255], (y * width + x) * 4)
    }
  }

  return { width, height, channels: 4, data }
}

const redAt = (pixels: Pixels, out: Uint8ClampedArray, x: number, y: number): number => out[(y * pixels.width + x) * 4]

describe('blurs', () => {
  it('keeps a flat picture flat and spreads a dot as a normalised gaussian', () => {
    const flat = gaussianPlane(new Float32Array(25).fill(0.4), 5, 5, 1.2)
    flat.forEach((value) => expect(value).toBeCloseTo(0.4, 5))
    const dot = new Float32Array(81)
    dot[40] = 1
    const blurred = gaussianPlane(dot, 9, 9, 1)
    expect(blurred.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 4)
    // A gaussian of sigma 1, normalised over its seven taps: the centre weighs 0.39907 each way, the next 0.24204.
    expect(blurred[40]).toBeCloseTo(0.39907 ** 2, 4)
    expect(blurred[41]).toBeCloseTo(0.39907 * 0.24204, 4)
  })

  it('approximates a wide gaussian with box passes, keeping the total', () => {
    const dot = new Float32Array(61 * 61)
    dot[30 * 61 + 30] = 1
    const blurred = gaussianPlane(dot, 61, 61, 4)
    expect(blurred.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 3)
    // Close to a true gaussian of sigma 4 at its centre (1 / (2π·16) ≈ 0.00995).
    expect(blurred[30 * 61 + 30]).toBeGreaterThan(0.0085)
    expect(blurred[30 * 61 + 30]).toBeLessThan(0.0115)
  })

  it('does not darken an edge next to transparency', () => {
    const data = new Uint8ClampedArray(4 * 4)
    data.set([200, 100, 50, 255, 200, 100, 50, 255, 0, 0, 0, 0, 0, 0, 0, 0])
    const out = applyFilter({ width: 4, height: 1, channels: 4, data }, checkFilter('gaussianBlur', { radius: 1 }))
    // The second pixel turns half transparent but keeps its colour.
    expect([out[4], out[5], out[6]]).toEqual([200, 100, 50])
    expect(out[7]).toBeLessThan(255)
  })

  it('streaks along the angle with running sums, even across rows', () => {
    const plane = new Float32Array(21 * 21)
    plane[10 * 21 + 10] = 1
    const across = motionPlane(plane, 21, 21, 0, 5)
    expect(across[10 * 21 + 8]).toBeCloseTo(0.2, 5)
    expect(across[10 * 21 + 12]).toBeCloseTo(0.2, 5)
    expect(across[10 * 21 + 13]).toBeCloseTo(0, 5)
    expect(across[9 * 21 + 10]).toBeCloseTo(0, 5)
    const down = motionPlane(plane, 21, 21, 90, 5)
    expect(down[8 * 21 + 10]).toBeCloseTo(0.2, 5)
    const slant = motionPlane(plane, 21, 21, 45, 6)
    expect(slant.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 1)
    // Up and to the right on screen (y down) from the dot, not down and to the right.
    expect(slant[8 * 21 + 12]).toBeGreaterThan(slant[12 * 21 + 12] + 0.02)
  })

  it('leaves a flat area mid-gray in a high pass', () => {
    const pixels = grayPixels(8, 8, () => 30)
    const out = applyFilter(pixels, checkFilter('highPass', { radius: 2 }))
    expect(redAt(pixels, out, 4, 4)).toBe(128)
  })
})

describe('sharpening', () => {
  it('Unsharp Mask pushes an edge apart by the amount, and the threshold spares small steps', () => {
    const pixels = grayPixels(10, 3, (x) => (x < 5 ? 100 : 150))
    const sharp = applyFilter(pixels, checkFilter('unsharpMask', { amount: 100, radius: 1, threshold: 0 }))
    expect(redAt(pixels, sharp, 4, 1)).toBeLessThan(100)
    expect(redAt(pixels, sharp, 5, 1)).toBeGreaterThan(150)
    expect(redAt(pixels, sharp, 0, 1)).toBe(100)
    const spared = applyFilter(pixels, checkFilter('unsharpMask', { amount: 100, radius: 1, threshold: 30 }))
    expect(redAt(pixels, spared, 4, 1)).toBe(100)
  })

  it('Smart Sharpen keeps within a little of its neighbours, so no halos', () => {
    const pixels = grayPixels(10, 3, (x) => (x < 5 ? 100 : 150))
    const sharp = applyFilter(pixels, checkFilter('smartSharpen', { amount: 500, radius: 2, reduceNoise: 0 }))
    expect(redAt(pixels, sharp, 4, 1)).toBeLessThan(100)
    expect(redAt(pixels, sharp, 4, 1)).toBeGreaterThanOrEqual(94)
    expect(redAt(pixels, sharp, 5, 1)).toBeLessThanOrEqual(156)
  })
})

describe('noise', () => {
  it('Median takes out a speck and keeps an edge', () => {
    const plane = new Uint8Array(25).fill(50)
    plane[12] = 255
    expect(medianChannel(plane, 5, 5, 1)[12]).toBe(50)
    const edge = Uint8Array.from({ length: 36 }, (_, i) => (i % 6 < 3 ? 0 : 200))
    const kept = medianChannel(edge, 6, 6, 1)
    expect([kept[14], kept[15]]).toEqual([0, 200])
  })

  it('Median finds the middle value of a window with a running histogram', () => {
    const values = Uint8Array.from({ length: 49 }, (_, i) => (i * 37) % 256)
    const out = medianChannel(values, 7, 7, 3)
    // The centre pixel's window is the whole picture.
    expect(out[24]).toBe([...values].sort((a, b) => a - b)[24])
  })

  it('Reduce Noise evens out a noisy flat area and keeps a strong edge', () => {
    const noisy = grayPixels(24, 24, (x, y) => (x < 12 ? 60 : 190) + (((x * 7 + y * 13) % 5) - 2) * 6)
    const out = applyFilter(noisy, checkFilter('reduceNoise', { strength: 8, preserveDetails: 0, colorNoise: 0 }))
    const spread = (values: number[]) => Math.max(...values) - Math.min(...values)
    const before = [0, 1, 2, 3, 4].map((y) => redAt(noisy, noisy.data, 5, y + 8))
    const after = [0, 1, 2, 3, 4].map((y) => redAt(noisy, out, 5, y + 8))
    expect(spread(after)).toBeLessThan(spread(before) / 2)
    expect(redAt(noisy, out, 6, 12)).toBeLessThan(80)
    expect(redAt(noisy, out, 17, 12)).toBeGreaterThan(170)
    expect(applyFilter(noisy, checkFilter('reduceNoise', { strength: 0, colorNoise: 0 }))).toEqual(noisy.data)
  })

  it('Add Noise is the same pattern for a piece as for the whole', () => {
    const pixels = grayPixels(8, 8, () => 128)
    const spec = checkFilter('addNoise', { amount: 40, seed: 7 })
    const whole = applyFilter(pixels, spec)
    const piece = applyFilter(grayPixels(4, 4, () => 128), spec, [4, 4])
    expect(piece[0]).toBe(whole[(4 * 8 + 4) * 4])
    expect(whole.some((value, i) => i % 4 === 0 && value !== 128)).toBe(true)
  })
})

describe('filter settings', () => {
  it('fills in defaults and refuses values outside the ranges', () => {
    expect(checkFilter('unsharpMask', { amount: 80 })).toEqual({ kind: 'unsharpMask', amount: 80, radius: 1, threshold: 0 })
    expect(checkFilter('median', { radius: 2.6 })).toMatchObject({ radius: 3 })
    expect(() => checkFilter('gaussianBlur', { radius: 0 })).toThrow(/radius must be from 0.1 to 250/)
    expect(() => checkFilter('addNoise', { gaussian: 'yes' })).toThrow(/true or false/)
    expect(() => checkFilter('motionBlur', { strength: 1 })).toThrow(/no setting/)
  })

  it('knows how far each filter reads, and scales sizes for a reduced preview', () => {
    const spec: FilterSpec = checkFilter('gaussianBlur', { radius: 10 })
    expect(filterReach(spec)).toBe(32)
    expect(filterReach(checkFilter('addNoise'))).toBe(0)
    expect(scaledFilter(spec, 0.5)).toMatchObject({ radius: 5 })
    expect(scaledFilter(checkFilter('unsharpMask', { amount: 200 }), 0.5)).toMatchObject({ amount: 200, radius: 0.5 })
  })

  it('reads the filter Hermes names', () => {
    expect(filterKindFrom('Sharpen')).toBe('unsharpMask')
    expect(filterKindFrom('gaussian blur')).toBe('gaussianBlur')
    expect(filterKindFrom('denoise')).toBe('reduceNoise')
    expect(() => filterKindFrom('oil paint')).toThrow(/kind is one of/)
  })

  it('filters a mask as gray', () => {
    const mask: Pixels = { width: 3, height: 1, channels: 1, data: Uint8ClampedArray.from([0, 255, 0]) }
    const out = applyFilter(mask, checkFilter('gaussianBlur', { radius: 1 }))
    expect(out[1]).toBeLessThan(255)
    expect(out[0]).toBeGreaterThan(0)
  })
})
