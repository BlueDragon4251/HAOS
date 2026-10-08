import { describe, expect, it } from 'vitest'
import { luminance, toHsl } from '../../../../shared/theme.ts'
import { grayRampOf, heraldPalette, rampOf } from './palette.ts'

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

describe('grayRampOf', () => {
  it('runs from white to black, lightest first', () => {
    const ramp = grayRampOf('#050f33')
    const order = [0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000] as const

    expect(ramp[0]).toBe('#ffffff')
    expect(ramp[1000]).toBe('#000000')

    for (let i = 1; i < order.length; i++) {
      expect(luminance(ramp[order[i]])).toBeLessThan(luminance(ramp[order[i - 1]]))
    }
  })

  it("takes the background's hue, so the dark chrome is tinted like Herald's glass", () => {
    const { h, s } = toHsl(grayRampOf('#050f33')[800])

    expect(Math.abs(h - toHsl('#050f33').h)).toBeLessThan(2)
    expect(s).toBeGreaterThan(0.1)
  })
})

describe('heraldPalette', () => {
  it('sets only the primary and gray ramps', () => {
    expect(Object.keys(heraldPalette({ accent: '#e6b84a', background: '#07080a' }))).toEqual(['primary', 'gray'])
  })
})
