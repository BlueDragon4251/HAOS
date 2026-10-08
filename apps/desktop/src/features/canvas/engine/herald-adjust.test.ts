import { describe, expect, it } from 'vitest'
import { defaultAdjustment, defaultHeraldAdjustment, HERALD_ADJUSTMENT_KINDS, type HeraldAdjustment, type SelectiveColorSettings } from '../../../../shared/canvas/comp-format.ts'
import { adjustPixel, hueSaturation, lum, type RGB3, rgbToHsl } from './adjust-math.ts'
import { cubeText, lookUp, parseCube, tablePosition } from './color-table.ts'
import { adjustHerald, brightnessContrastCurve, channelMixer, photoFilter, posterize, selectiveColor, selectiveWeights, standInFor, standInIsExact, threshold, vibrance } from './herald-adjust.ts'

/** Colours across the cube, with some 8-bit steps between. */
const SAMPLES: RGB3[] = []

for (const r of [0, 0.13, 0.5, 0.77, 1]) {
  for (const g of [0, 0.31, 0.6, 1]) {
    for (const b of [0, 0.25, 0.9]) {
      SAMPLES.push([r, g, b])
    }
  }
}

const near = (a: RGB3, b: RGB3, tolerance = 1e-9) => a.every((value, i) => Math.abs(value - b[i]) <= tolerance)
const with_ = <K extends HeraldAdjustment['kind']>(kind: K, change: Record<string, unknown>) => ({ ...defaultHeraldAdjustment(kind), ...change }) as Extract<HeraldAdjustment, { kind: K }>

describe('Brightness/Contrast', () => {
  it('changes nothing at 0, and keeps black and white while brightness bends the middle', () => {
    expect(brightnessContrastCurve(0, 0).every((point) => Math.abs(point.y - point.x) < 1e-9)).toBe(true)
    expect(SAMPLES.every((c) => near(adjustHerald(c, with_('Brightness/Contrast', {})), c, 1e-6))).toBe(true)
    const brighter = with_('Brightness/Contrast', { brightness: 150 })
    expect(adjustHerald([0.5, 0.5, 0.5], brighter)[0]).toBeCloseTo(0.75, 2)
    expect(adjustHerald([0, 0, 0], brighter)).toEqual([0, 0, 0])
    expect(adjustHerald([1, 1, 1], brighter)[0]).toBeCloseTo(1, 6)
  })

  it('steepens around the middle gray, or flattens towards it', () => {
    const steeper = with_('Brightness/Contrast', { contrast: 100 })
    expect(adjustHerald([0.25, 0.25, 0.25], steeper)[0]).toBeLessThan(0.15)
    expect(adjustHerald([0.75, 0.75, 0.75], steeper)[0]).toBeGreaterThan(0.85)
    expect(adjustHerald([0.5, 0.5, 0.5], steeper)[0]).toBeCloseTo(0.5, 3)
    const flatter = with_('Brightness/Contrast', { contrast: -50 })
    expect(adjustHerald([0, 0, 0], flatter)[0]).toBeCloseTo(0.25, 3)
    expect(adjustHerald([1, 1, 1], flatter)[0]).toBeCloseTo(0.75, 3)
  })

  it('stands in as Curves that make exactly the same change', () => {
    for (const settings of [with_('Brightness/Contrast', { brightness: 60, contrast: 35 }), with_('Brightness/Contrast', { brightness: -120, contrast: -40 })]) {
      const standIn = standInFor(settings)
      expect(standIn.kind).toBe('Curves')
      expect(standIn.curves.channels[0]).toHaveLength(32)
      expect(SAMPLES.every((c) => near(adjustHerald(c, settings), adjustPixel(c, standIn), 0))).toBe(true)
    }
  })
})

describe('Vibrance', () => {
  it('without vibrance is Hue/Saturation, and stands in as it exactly', () => {
    const settings = with_('Vibrance', { saturation: 30 })
    const standIn = standInFor(settings)
    expect(standIn).toMatchObject({ kind: 'Hue/Saturation', saturation: 30, hue: 0, lightness: 0 })
    expect(SAMPLES.every((c) => near(vibrance(c, settings), hueSaturation(c, { hue: 0, saturation: 30, lightness: 0, colorize: false }), 0))).toBe(true)
    expect(SAMPLES.every((c) => near(adjustHerald(c, settings), adjustPixel(c, standIn), 0))).toBe(true)
  })

  it('moves dull colours further than vivid ones, sparing skin tones', () => {
    const settings = with_('Vibrance', { vibrance: 60 })
    const gain = (c: RGB3) => rgbToHsl(vibrance(c, settings))[1] - rgbToHsl(c)[1]
    expect(gain([0.45, 0.5, 0.6])).toBeGreaterThan(gain([0.1, 0.3, 0.95]))
    // Equally dull, a skin tone gains less than a blue.
    expect(gain([0.62, 0.52, 0.45])).toBeLessThan(gain([0.45, 0.52, 0.62]))
    // All the way down, a dull colour turns gray.
    const out = vibrance([0.5, 0.5, 0.55], with_('Vibrance', { vibrance: -100 }))
    expect(Math.max(...out) - Math.min(...out)).toBeLessThan(0.002)
  })
})

describe('Photo Filter', () => {
  it('tints by the density and stands in as Levels exactly without Preserve Luminosity', () => {
    const settings = with_('Photo Filter', { color: { red: 1, green: 0.5, blue: 0 }, density: 40, preserveLuminosity: false })
    expect(photoFilter([1, 1, 1], settings)).toEqual([1, 0.8, 0.6])
    const standIn = standInFor(settings)
    expect(standIn.kind).toBe('Levels')
    expect(standIn.levels.ranges[2].outputWhite).toBeCloseTo(204)
    // Levels runs through 32-bit tables: the same change, to far below a level.
    expect(SAMPLES.every((c) => near(adjustHerald(c, settings), adjustPixel(c, standIn), 1e-6))).toBe(true)
  })

  it('keeps the brightness with Preserve Luminosity (with no exact stand-in)', () => {
    const settings = with_('Photo Filter', {})
    const c: RGB3 = [0.4, 0.5, 0.6]
    expect(lum(photoFilter(c, settings))).toBeCloseTo(lum(c), 6)
    expect(photoFilter(c, settings)[0]).toBeGreaterThan(c[0])
    expect(standInIsExact(settings)).toBe(false)
  })
})

describe('Channel Mixer, Selective Color, Posterize and Threshold', () => {
  it('mixes channels, with a constant and a monochrome row', () => {
    const swap = with_('Channel Mixer', { red: { red: 0, green: 0, blue: 100, constant: 0 }, blue: { red: 100, green: 0, blue: 0, constant: 10 } })
    expect(channelMixer([0.2, 0.4, 0.6], swap)).toEqual([0.6, 0.4, expect.closeTo(0.3, 9)])
    expect(channelMixer([0.2, 0.4, 0.6], with_('Channel Mixer', {}))).toEqual([0.2, 0.4, 0.6])
    expect(channelMixer([1, 0.5, 0], with_('Channel Mixer', { monochrome: true }))).toEqual([0.6, 0.6, 0.6])
  })

  it('splits a colour into its ranges', () => {
    expect(selectiveWeights([1, 0.5, 0])).toMatchObject({ reds: 0.5, yellows: 0.5, whites: 0, blacks: 0, neutrals: 0 })
    expect(selectiveWeights([0.5, 0.5, 0.5])).toMatchObject({ neutrals: 1, reds: 0 })
    expect(selectiveWeights([1, 1, 1]).whites).toBe(1)
    expect(selectiveWeights([0.1, 0.1, 0.2]).blacks).toBeCloseTo(0.6)
  })

  it('changes inks relative to what there is, or by the amount itself', () => {
    const reds = (inks: Record<string, number>, absolute = false) => ({ ...with_('Selective Color', { absolute }), reds: { cyan: 0, magenta: 0, yellow: 0, black: 0, ...inks } }) as SelectiveColorSettings
    // Pure red has no cyan to take away; taking its yellow leaves magenta.
    expect(selectiveColor([1, 0, 0], reds({ cyan: -100 }))).toEqual([1, 0, 0])
    expect(selectiveColor([1, 0, 0], reds({ yellow: -100 }))).toEqual([1, 0, 1])
    expect(selectiveColor([1, 0, 0], reds({ cyan: 50 }, true))).toEqual([0.5, 0, 0])
    const neutral = { ...with_('Selective Color', { absolute: true }), neutrals: { cyan: 0, magenta: 0, yellow: 0, black: 20 } } as SelectiveColorSettings
    expect(selectiveColor([0.5, 0.5, 0.5], neutral).map((v) => Math.round(v * 1000) / 1000)).toEqual([0.3, 0.3, 0.3])
    expect(SAMPLES.every((c) => near(selectiveColor(c, with_('Selective Color', {})), c))).toBe(true)
  })

  it('posterizes into even bands and thresholds by brightness, steady on the steps', () => {
    const ramp = Array.from({ length: 256 }, (_, i) => posterize([i / 255, 0, 0], { levels: 4 })[0])
    expect([...new Set(ramp)]).toEqual([0, 1 / 3, 2 / 3, 1])
    expect(posterize([64 / 255, 0, 0], { levels: 4 })[0]).toBeCloseTo(1 / 3)
    expect(posterize([0.49, 0.5, 1], { levels: 2 })).toEqual([0, 1, 1])
    // On a step of five levels (51 of 255) a channel reaches it, however it was rounded on the way.
    expect(posterize([51 / 255 - 1e-4, 0.2, 51 / 255 + 1e-4], { levels: 5 })).toEqual([0.25, 0.25, 0.25])
    expect(threshold([127 / 255, 127 / 255, 127 / 255], { level: 128 })).toEqual([0, 0, 0])
    expect(threshold([128 / 255 - 2e-4, 128 / 255, 128 / 255], { level: 128 })).toEqual([1, 1, 1])
  })
})

describe('stand-ins', () => {
  it('change nothing where Compositor has no equal', () => {
    for (const kind of HERALD_ADJUSTMENT_KINDS) {
      const settings = defaultHeraldAdjustment(kind)
      const standIn = standInFor(settings)

      if (!standInIsExact(settings)) {
        expect(standIn, kind).toEqual(defaultAdjustment('Levels'))
      }

      expect(SAMPLES.every((c) => near(adjustPixel(c, standIn), c, 1e-6)) || standInIsExact(settings), kind).toBe(true)
    }
  })
})

describe('colour tables', () => {
  const encode = (text: string) => new TextEncoder().encode(text)
  const swap = parseCube(encode(cubeText(5, (r, g, b) => [b, g, r], 'Swap')))

  it('reads a .cube table and looks colours up between its entries', () => {
    expect(swap).toMatchObject({ size: 5, title: 'Swap' })
    expect(lookUp([0.1, 0.4, 0.8], swap).map((v) => Math.round(v * 1e5) / 1e5)).toEqual([0.8, 0.4, 0.1])
    const identity = parseCube(encode(cubeText(2, (r, g, b) => [r, g, b])))
    expect(near(lookUp([0.3, 0.6, 0.9], identity), [0.3, 0.6, 0.9], 1e-6)).toBe(true)
    // A table that only darkens shows its interpolation between entries.
    const half = parseCube(encode(cubeText(3, (r, g, b) => [r / 2, g / 2, b / 2])))
    expect(lookUp([0.25, 0.25, 0.25], half)[0]).toBeCloseTo(0.125, 6)
  })

  it('stretches its domain and holds colours inside it', () => {
    const text = `# Made by hand\nTITLE "Wide"\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 2 2 2\nLUT_3D_SIZE 2\n${[0, 1].flatMap((b) => [0, 1].flatMap((g) => [0, 1].map((r) => `${r} ${g} ${b}`))).join('\n')}\n`
    const wide = parseCube(encode(text))
    expect(tablePosition([1, 0.5, 4], wide)).toEqual([0.5, 0.25, 1])
    expect(lookUp([1, 1, 1], wide)[0]).toBeCloseTo(0.5, 6)
  })

  it('refuses what is not a 3D table it can hold, saying why', () => {
    const rows = (count: number) => Array.from({ length: count }, () => '0 0 0').join('\n')
    expect(() => parseCube(encode(`LUT_3D_SIZE 2\n${rows(7)}`))).toThrow(/7 colours where/)
    expect(() => parseCube(encode(`LUT_3D_SIZE 2\n${rows(9)}`))).toThrow(/more than/)
    expect(() => parseCube(encode(`LUT_1D_SIZE 16\n${rows(16)}`))).toThrow(/1D table/)
    expect(() => parseCube(encode(`LUT_3D_SIZE 66\n`))).toThrow(/2 to 65/)
    expect(() => parseCube(encode(`LUT_3D_SIZE 2\n0 0\n${rows(7)}`))).toThrow(/three numbers/)
    expect(() => parseCube(encode(rows(8)))).toThrow(/before its LUT_3D_SIZE/)
    expect(() => parseCube(encode('TITLE "Empty"\n'))).toThrow(/no LUT_3D_SIZE/)
    expect(() => parseCube(encode(`DOMAIN_MIN 1 0 0\nDOMAIN_MAX 1 1 1\nLUT_3D_SIZE 2\n${rows(8)}`))).toThrow(/DOMAIN_MAX/)
  })

  it('looks colours up through a Color Lookup layer, and changes nothing before it has a table', () => {
    const settings = with_('Color Lookup', { name: 'Swap.cube', size: 5 })
    expect(adjustHerald([0.2, 0.5, 0.9], settings, swap).map((v) => Math.round(v * 1e5) / 1e5)).toEqual([0.9, 0.5, 0.2])
    expect(adjustHerald([0.2, 0.5, 0.9], with_('Color Lookup', {}), null)).toEqual([0.2, 0.5, 0.9])
  })
})
