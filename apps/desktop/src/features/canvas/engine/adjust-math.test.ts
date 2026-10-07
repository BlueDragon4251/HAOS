import { describe, expect, it } from 'vitest'
import { defaultAdjustment, identityLevels, identityRange } from '../../../../shared/canvas/comp-format.ts'
import {
  adjustPixel,
  applyTables,
  BALANCE_REACH,
  blackWhite,
  blurPlan,
  colorBalance,
  curveTable,
  exposure,
  gaussianTaps,
  gradientMap,
  grainAt,
  hslToRgb,
  hueSaturation,
  levelRange,
  levelsTables,
  luma,
  motionDirection,
  motionPasses,
  MOTION_TAPS,
  noiseAt,
  NOISE_REACH,
  type RGB3,
  rgbToHsl,
  srgbToLinear,
  tonalWeights
} from './adjust-math.ts'

const near = (actual: number[], expected: number[], digits = 4) => actual.forEach((value, i) => expect(value).toBeCloseTo(expected[i], digits))

const SAMPLES: RGB3[] = [
  [0, 0, 0],
  [1, 1, 1],
  [0.5, 0.5, 0.5],
  [0.9, 0.2, 0.1],
  [0.1, 0.7, 0.3],
  [0.2, 0.3, 0.95],
  [0.6, 0.55, 0.05]
]

describe('colour spaces', () => {
  it('goes to HSL and back', () => {
    for (const colour of SAMPLES) {
      const [h, s, l] = rgbToHsl(colour)
      near(hslToRgb(h, s, l), colour, 6)
    }
  })

  it('reads pure hues where they belong', () => {
    expect(rgbToHsl([1, 0, 0])[0]).toBeCloseTo(0)
    expect(rgbToHsl([0, 1, 0])[0]).toBeCloseTo(120)
    expect(rgbToHsl([0, 0, 1])[0]).toBeCloseTo(240)
  })
})

describe('Hue/Saturation', () => {
  const none = { hue: 0, saturation: 0, lightness: 0, colorize: false }

  it('changes nothing at its defaults', () => {
    SAMPLES.forEach((colour) => near(hueSaturation(colour, none), colour, 6))
  })

  it('turns the hue, fades to gray and pulls towards white or black', () => {
    near(hueSaturation([1, 0, 0], { ...none, hue: 120 }), [0, 1, 0])
    near(hueSaturation([1, 0, 0], { ...none, hue: -120 }), [0, 0, 1])
    const gray = hueSaturation([0.9, 0.2, 0.1], { ...none, saturation: -100 })
    expect(gray[0]).toBeCloseTo(gray[1], 6)
    expect(gray[1]).toBeCloseTo(gray[2], 6)
    near(hueSaturation([0.3, 0.6, 0.2], { ...none, lightness: 100 }), [1, 1, 1])
    near(hueSaturation([0.3, 0.6, 0.2], { ...none, lightness: -100 }), [0, 0, 0])
  })

  it('saturates fully at +100 and colorizes in one hue', () => {
    const [, s] = rgbToHsl(hueSaturation([0.6, 0.5, 0.45], { ...none, saturation: 100 }))
    expect(s).toBeCloseTo(1)
    const [h, sat, l] = rgbToHsl(hueSaturation([0.3, 0.6, 0.2], { hue: 200, saturation: 40, lightness: 0, colorize: true }))
    expect(h).toBeCloseTo(200, 3)
    expect(sat).toBeCloseTo(0.4, 4)
    expect(l).toBeCloseTo(rgbToHsl([0.3, 0.6, 0.2])[2], 6)
  })
})

describe('Levels and Curves', () => {
  it('maps a range: black and white to the ends, gamma on the midtones, then the output range', () => {
    const range = { ...identityRange(), black: 64, white: 192 }
    expect(levelRange(64 / 255, range)).toBeCloseTo(0)
    expect(levelRange(128 / 255, range)).toBeCloseTo(0.5, 2)
    expect(levelRange(192 / 255, range)).toBeCloseTo(1)
    expect(levelRange(0.5, { ...identityRange(), gamma: 2 })).toBeCloseTo(Math.sqrt(0.5), 6)
    expect(levelRange(1, { ...identityRange(), outputWhite: 128 })).toBeCloseTo(128 / 255, 6)
  })

  it('runs each channel first, then the RGB range', () => {
    const levels = identityLevels()
    levels.ranges[1] = { ...identityRange(), black: 128 }
    levels.ranges[0] = { ...identityRange(), outputWhite: 128 }
    const tables = levelsTables(levels)
    near(applyTables([1, 1, 0.5], tables), [128 / 255, 128 / 255, 64 / 255], 3)
    near(applyTables([0.5, 0, 0], tables), [0, 0, 0], 3)
  })

  it('leaves colour alone with identity tables', () => {
    const tables = levelsTables(identityLevels())
    SAMPLES.forEach((colour) => near(applyTables(colour, tables), colour, 6))
  })

  it('draws a curve through its points, smooth and never overshooting, flat past its ends', () => {
    const identity = curveTable([
      { x: 0, y: 0 },
      { x: 255, y: 255 }
    ])
    identity.forEach((value, i) => expect(value).toBeCloseTo(i / 255, 6))

    const s = curveTable([
      { x: 0, y: 0 },
      { x: 64, y: 52 },
      { x: 192, y: 204 },
      { x: 255, y: 255 }
    ])
    expect(s[64] * 255).toBeCloseTo(52, 4)
    expect(s[192] * 255).toBeCloseTo(204, 4)

    for (let i = 1; i < 256; i++) {
      expect(s[i]).toBeGreaterThanOrEqual(s[i - 1] - 1e-7)
    }

    // A steep step stays between its two levels.
    const step = curveTable([
      { x: 0, y: 0 },
      { x: 100, y: 10 },
      { x: 110, y: 240 },
      { x: 255, y: 250 }
    ])
    step.forEach((value) => expect(value * 255).toBeLessThanOrEqual(250 + 1e-4))
    expect(step[105] * 255).toBeGreaterThan(10)
    expect(step[105] * 255).toBeLessThan(240)

    const clipped = curveTable([
      { x: 40, y: 30 },
      { x: 200, y: 220 }
    ])
    expect(clipped[0] * 255).toBeCloseTo(30, 4)
    expect(clipped[255] * 255).toBeCloseTo(220, 4)
  })
})

describe('Exposure, Gradient Map, Invert', () => {
  it('works in linear light', () => {
    const lighter = exposure([0.2, 0.4, 0.6], { exposure: 1, offset: 0, gamma: 1 })
    near(lighter.map(srgbToLinear), [0.2, 0.4, 0.6].map((v) => Math.min(1, srgbToLinear(v) * 2)), 5)
    SAMPLES.forEach((colour) => near(exposure(colour, { exposure: 0, offset: 0, gamma: 1 }), colour, 6))
    near(exposure([0.5, 0.5, 0.5], { exposure: 0, offset: 0, gamma: 2 }).map(srgbToLinear), Array(3).fill(Math.sqrt(srgbToLinear(0.5))), 5)
  })

  it('maps brightness between two colours', () => {
    const settings = { shadows: { red: 0.1, green: 0, blue: 0.4 }, highlights: { red: 1, green: 0.9, blue: 0.6 }, reversed: false }
    near(gradientMap([0, 0, 0], settings), [0.1, 0, 0.4])
    near(gradientMap([1, 1, 1], settings), [1, 0.9, 0.6])
    near(gradientMap([0, 0, 0], { ...settings, reversed: true }), [1, 0.9, 0.6])
    const t = luma([0.9, 0.2, 0.1])
    near(gradientMap([0.9, 0.2, 0.1], settings), [0.1 + 0.9 * t, 0.9 * t, 0.4 + 0.2 * t])
  })

  it('inverts', () => {
    near(adjustPixel([0.2, 0.5, 1], defaultAdjustment('Invert')), [0.8, 0.5, 0])
  })
})

describe('Black & White and Color Balance', () => {
  const defaults = defaultAdjustment('Black & White').blackWhiteSettings!

  it('turns each colour family to its own gray', () => {
    near(blackWhite([1, 0, 0], defaults), [0.4, 0.4, 0.4])
    near(blackWhite([1, 1, 0], defaults), [0.6, 0.6, 0.6])
    near(blackWhite([0, 0, 1], defaults), [0.2, 0.2, 0.2])
    near(blackWhite([1, 0, 1], defaults), [0.8, 0.8, 0.8])
    near(blackWhite([1, 1, 1], defaults), [1, 1, 1])
    near(blackWhite([0.3, 0.3, 0.3], defaults), [0.3, 0.3, 0.3])
  })

  it('tints the gray, keeping it as the lightness', () => {
    const tinted = blackWhite([1, 1, 0], { ...defaults, tint: true, tintHue: 30, tintSaturation: 50 })
    const [h, s, l] = rgbToHsl(tinted)
    expect(h).toBeCloseTo(30, 3)
    expect(s).toBeCloseTo(0.5, 4)
    expect(l).toBeCloseTo(0.6, 6)
  })

  it('weights tones so they overlap', () => {
    near(tonalWeights(0), [1, 0, 0])
    near(tonalWeights(0.5), [1 - 0.9259, 1, 1 - 0.9259], 3)
    near(tonalWeights(1), [0, 0, 1])
  })

  it('shifts channels by tone, and can keep the brightness', () => {
    const balance = { ...defaultAdjustment('Color Balance').colorBalanceSettings!, preserveLuminosity: false }
    SAMPLES.forEach((colour) => near(colorBalance(colour, balance), colour, 6))
    const warmer = colorBalance([0.5, 0.5, 0.5], { ...balance, midCyanRed: 40 })
    expect(warmer[0]).toBeCloseTo(0.5 + 0.4 * BALANCE_REACH * tonalWeights(0.5)[1], 6)
    expect(warmer[1]).toBeCloseTo(0.5)
    const kept = colorBalance([0.5, 0.5, 0.5], { ...balance, midCyanRed: 40, preserveLuminosity: true })
    expect(0.3 * kept[0] + 0.59 * kept[1] + 0.11 * kept[2]).toBeCloseTo(0.5, 5)
    expect(kept[0]).toBeGreaterThan(kept[1])
  })
})

describe('identity defaults', () => {
  it('leaves colour alone for the kinds that start as no change', () => {
    for (const kind of ['Hue/Saturation', 'Levels', 'Curves', 'Exposure', 'Color Balance', 'Gaussian Blur', 'Motion Blur'] as const) {
      SAMPLES.forEach((colour) => near(adjustPixel(colour, defaultAdjustment(kind)), colour, 5))
    }
  })
})

describe('noise and grain', () => {
  const settings = { amount: 50, gaussian: false, monochromatic: false, seed: 7 }

  it('is fixed by the seed and the pixel', () => {
    expect(noiseAt(10, 20, settings)).toEqual(noiseAt(10, 20, settings))
    expect(noiseAt(10, 20, settings)).not.toEqual(noiseAt(11, 20, settings))
    expect(noiseAt(10, 20, settings)).not.toEqual(noiseAt(10, 20, { ...settings, seed: 8 }))
    const mono = noiseAt(3, 4, { ...settings, monochromatic: true })
    expect(mono[0]).toBe(mono[1])
    expect(mono[1]).toBe(mono[2])
  })

  it('spreads uniformly within the amount, around zero', () => {
    const reach = (settings.amount / 100) * NOISE_REACH
    let sum = 0
    let squares = 0
    let count = 0

    for (let y = 0; y < 64; y++) {
      for (let x = 0; x < 64; x++) {
        for (const value of noiseAt(x, y, settings)) {
          expect(Math.abs(value)).toBeLessThanOrEqual(reach)
          sum += value
          squares += value * value
          count++
        }
      }
    }

    expect(sum / count).toBeCloseTo(0, 2)
    // A uniform spread on ±reach has a variance of reach² / 3; the gaussian is made to match it.
    expect(squares / count).toBeCloseTo((reach * reach) / 3, 2)
    let gaussian = 0

    for (let i = 0; i < 4096; i++) {
      gaussian += noiseAt(i % 64, Math.floor(i / 64), { ...settings, gaussian: true })[0] ** 2
    }

    expect(gaussian / 4096).toBeCloseTo((reach * reach) / 3, 2)
  })

  it('makes smooth grain that stays put, strongest in the midtones', () => {
    const grain = { amount: 50, size: 8, roughness: 0, seed: 3 }
    expect(grainAt(12.5, 40.5, 0.5, grain)).toBe(grainAt(12.5, 40.5, 0.5, grain))
    // A quarter pixel apart on 8-pixel grain, the value barely moves; neighbouring cells differ far more.
    expect(Math.abs(grainAt(12.5, 40.5, 0.5, grain) - grainAt(12.75, 40.5, 0.5, grain))).toBeLessThan(0.05)
    expect(Math.abs(grainAt(12.5, 40.5, 0.5, { ...grain, amount: 0 }))).toBe(0)
    expect(Math.abs(grainAt(12.5, 40.5, 0.02, grain))).toBeLessThan(Math.abs(grainAt(12.5, 40.5, 0.5, grain)) + 1e-9)
  })
})

describe('blurs', () => {
  it('builds gaussian taps that add up to one with the right spread', () => {
    for (const sigma of [0.6, 1.5, 3.2]) {
      const { offsets, weights } = gaussianTaps(sigma)
      const total = weights[0] + 2 * weights.slice(1).reduce((sum, w) => sum + w, 0)
      expect(total).toBeCloseTo(1, 6)
      // Each merged tap stands for two texels; the spread is close to sigma² (the cut tail is tiny).
      const variance = 2 * offsets.slice(1).reduce((sum, offset, i) => sum + weights[i + 1] * offset * offset, 0)
      expect(Math.sqrt(variance)).toBeCloseTo(sigma, 0)
    }
  })

  it('reduces big blurs and keeps the total spread', () => {
    expect(blurPlan(2)).toEqual({ factor: 1, sigma: 2 })

    for (const sigma of [9, 40, 250]) {
      const plan = blurPlan(sigma)
      expect(plan.factor).toBeGreaterThan(1)
      expect(plan.sigma).toBeLessThan(4)
      const variance = plan.factor ** 2 * plan.sigma ** 2 + (plan.factor ** 2 - 1) / 12 + plan.factor ** 2 / 6
      expect(Math.sqrt(variance)).toBeCloseTo(sigma, 3)
    }
  })

  it('streaks evenly over the distance in a few passes', () => {
    expect(motionPasses(60)).toHaveLength(1)
    expect(motionPasses(MOTION_TAPS * 3)).toHaveLength(2)
    expect(motionPasses(2000)).toHaveLength(2)

    for (const length of [5, 64, 300, 2000]) {
      const passes = motionPasses(length)
      let offsets = [0]

      for (const { taps, spacing } of passes) {
        offsets = offsets.flatMap((offset) => Array.from({ length: taps }, (_, i) => offset + (i - (taps - 1) / 2) * spacing))
      }

      offsets.sort((a, b) => a - b)
      const gaps = offsets.slice(1).map((offset, i) => offset - offsets[i])
      gaps.forEach((gap) => expect(gap).toBeCloseTo(passes[0].spacing, 6))
      expect(passes[0].spacing).toBeLessThanOrEqual(0.5)
      expect(passes.every((pass) => pass.taps <= MOTION_TAPS)).toBe(true)
      expect(offsets.at(-1)! - offsets[0] + passes[0].spacing).toBeCloseTo(length, 6)
    }

    near(motionDirection(90), [0, -1])
  })
})
