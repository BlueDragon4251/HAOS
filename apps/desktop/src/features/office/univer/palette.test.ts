import { describe, expect, it } from 'vitest'
import { luminance, parseHex, toHsl } from '../../../../shared/theme.ts'
import { beforeDarkMode, darkGrayRamp, heraldPalette, invertForDarkMode, lightGrayRamp, rampOf } from './palette.ts'

const distance = (a: string, b: string) => {
  const x = parseHex(a)!
  const y = parseHex(b)!

  return Math.max(Math.abs(x.r - y.r), Math.abs(x.g - y.g), Math.abs(x.b - y.b))
}

describe('rampOf', () => {
  it('puts the base colour at 600 and lightens below it, darkens above it', () => {
    const ramp = rampOf('#2f7dff')

    expect(ramp[600]).toBe('#2f7dff')
    expect(luminance(ramp[50])).toBeGreaterThan(luminance(ramp[300]))
    expect(luminance(ramp[300])).toBeGreaterThan(luminance(ramp[600]))
    expect(luminance(ramp[600])).toBeGreaterThan(luminance(ramp[900]))
  })

  it('falls back to Herald blue for a colour it cannot read', () => {
    expect(rampOf('var(--color-accent)')[600]).toBe('#2f7dff')
  })
})

describe('the dark-mode matrix', () => {
  it('turns white into black, as Univer does', () => {
    expect(invertForDarkMode('#ffffff')).toBe('#000000')
  })

  it('is undone by beforeDarkMode, so a chosen navy is what the canvas draws', () => {
    for (const navy of ['#0b1a4a', '#14244f', '#1f2d5c', '#4a5a85']) {
      expect(distance(invertForDarkMode(beforeDarkMode(navy)), navy)).toBeLessThanOrEqual(1)
    }
  })
})

describe('gray ramps', () => {
  it('runs light to dark for a light theme', () => {
    const ramp = lightGrayRamp('#f4f6fb')
    const order = [0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000] as const

    for (let i = 1; i < order.length; i++) {
      expect(luminance(ramp[order[i]])).toBeLessThan(luminance(ramp[order[i - 1]]))
    }
  })

  it("draws a dark theme's grid in its navy and tints the chrome with it", () => {
    const ramp = darkGrayRamp('#050f33')
    const canvas = invertForDarkMode(ramp[0])

    expect(luminance(ramp[0])).toBeGreaterThan(0.5)
    expect(luminance(canvas)).toBeLessThan(0.03)
    expect(Math.abs(toHsl(canvas).h - toHsl('#050f33').h)).toBeLessThan(6)
    expect(Math.abs(toHsl(ramp[800]).h - toHsl('#050f33').h)).toBeLessThan(2)
    expect(luminance(ramp[600])).toBeGreaterThan(luminance(ramp[900]))
  })

  it('picks the ramp for the scheme and leaves the other colours alone', () => {
    expect(Object.keys(heraldPalette({ accent: '#e6b84a', background: '#07080a', dark: true }))).toEqual(['primary', 'gray'])
    expect(heraldPalette({ accent: '#336699', background: '#ffffff', dark: false }).gray[0]).toBe('#ffffff')
  })
})
