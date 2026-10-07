import { describe, expect, it } from 'vitest'
import { type Gradient, GRADIENT_PRESETS, gradientAt, gradientPosition, gradientTable, lineAcross, midpointMix, sortedStops, TABLE_SIZE } from './gradient.ts'

const black: [number, number, number] = [0, 0, 0]
const white: [number, number, number] = [255, 255, 255]

/** Red to green to blue, half opaque in the middle, the mix to green pulled early. */
const ramp: Gradient = {
  name: 'Ramp',
  colours: [
    { at: 0, colour: [255, 0, 0], mid: 0.25 },
    { at: 0.5, colour: [0, 255, 0], mid: 0.5 },
    { at: 1, colour: [0, 0, 255], mid: 0.5 }
  ],
  opacities: [
    { at: 0, opacity: 1, mid: 0.5 },
    { at: 0.5, opacity: 0.5, mid: 0.5 },
    { at: 1, opacity: 1, mid: 0.5 }
  ]
}

describe('mixing between stops', () => {
  it('is half way at the midpoint and smooth either side', () => {
    expect(midpointMix(0.5, 0.5)).toBe(0.5)

    for (const mid of [0.1, 0.25, 0.8]) {
      expect(midpointMix(mid, mid)).toBeCloseTo(0.5, 10)
      expect(midpointMix(0, mid)).toBe(0)
      expect(midpointMix(1, mid)).toBe(1)
      expect(midpointMix(0.3, mid)).toBeLessThan(midpointMix(0.6, mid))
    }
  })

  it('reads colour and opacity apart, at the stops and between them', () => {
    expect(gradientAt(ramp, 0, black, white)).toEqual([255, 0, 0, 255])
    expect(gradientAt(ramp, 0.5, black, white)).toEqual([0, 255, 0, 127.5])
    // The midpoint between red and green is a quarter of the way (t = 0.125 overall).
    const [r, g] = gradientAt(ramp, 0.125, black, white)
    expect(r).toBeCloseTo(127.5)
    expect(g).toBeCloseTo(127.5)
    expect(gradientAt(ramp, 0.75, black, white)[3]).toBeCloseTo(191.25)
    // Before the first stop and after the last, the end colours hold.
    const late = { ...ramp, colours: ramp.colours.map((entry) => ({ ...entry, at: entry.at * 0.5 + 0.25 })) }
    expect(gradientAt(late, 0.1, black, white).slice(0, 3)).toEqual([255, 0, 0])
    expect(gradientAt(late, 0.95, black, white).slice(0, 3)).toEqual([0, 0, 255])
  })

  it('follows the foreground and background colours', () => {
    const fg = GRADIENT_PRESETS[0]
    expect(gradientAt(fg, 0, [10, 20, 30], [200, 210, 220]).slice(0, 3)).toEqual([10, 20, 30])
    expect(gradientAt(fg, 1, [10, 20, 30], [200, 210, 220]).slice(0, 3)).toEqual([200, 210, 220])
    // Fading to transparency keeps the colour all the way.
    const fade = GRADIENT_PRESETS[1]
    expect(gradientAt(fade, 0.9, [10, 20, 30], white)).toEqual([10, 20, 30, expect.closeTo(25.5, 5)])
  })

  it('puts stops in order and keeps them in range', () => {
    const sorted = sortedStops([
      { at: 0.8, mid: 0.99, opacity: 1 },
      { at: -0.2, mid: 0.01, opacity: 0 }
    ])
    expect(sorted.map((entry) => [entry.at, entry.mid])).toEqual([
      [0, 0.05],
      [0.8, 0.95]
    ])
  })

  it('tables the gradient both ways round', () => {
    const table = gradientTable(ramp, black, white)
    const reversed = gradientTable(ramp, black, white, true)
    expect(table.length).toBe(TABLE_SIZE * 4)
    expect([...table.subarray(0, 4)]).toEqual([255, 0, 0, 255])
    expect([...reversed.subarray(0, 4)]).toEqual([0, 0, 255, 255])
    expect([...reversed.subarray((TABLE_SIZE - 1) * 4)]).toEqual([255, 0, 0, 255])
  })
})

describe('gradient styles', () => {
  const line = { from: [0, 0] as [number, number], to: [10, 0] as [number, number] }

  it('runs linear along the line and reflected both ways from its start', () => {
    expect(gradientPosition({ ...line, style: 'linear' }, 5, 3)).toBeCloseTo(0.5)
    expect(gradientPosition({ ...line, style: 'linear' }, -2, 0)).toBe(0)
    expect(gradientPosition({ ...line, style: 'linear' }, 15, 0)).toBe(1)
    expect(gradientPosition({ ...line, style: 'reflected' }, -5, 0)).toBeCloseTo(0.5)
    expect(gradientPosition({ ...line, style: 'reflected' }, 5, 0)).toBeCloseTo(0.5)
  })

  it('rings out from the start radially, with the end a corner of the diamond', () => {
    expect(gradientPosition({ ...line, style: 'radial' }, 0, 5)).toBeCloseTo(0.5)
    expect(gradientPosition({ ...line, style: 'radial' }, 6, 8)).toBe(1)
    expect(gradientPosition({ ...line, style: 'diamond' }, 5, 0)).toBeCloseTo(0.5)
    expect(gradientPosition({ ...line, style: 'diamond' }, 2.5, -2.5)).toBeCloseTo(0.5)
    expect(gradientPosition({ ...line, style: 'diamond' }, 0, 10)).toBeCloseTo(1)
  })

  it('sweeps an angle gradient counterclockwise on screen from the line', () => {
    expect(gradientPosition({ ...line, style: 'angle' }, 10, 0)).toBeCloseTo(0)
    // Up the screen (y runs down) is a quarter turn counterclockwise.
    expect(gradientPosition({ ...line, style: 'angle' }, 0, -10)).toBeCloseTo(0.25)
    expect(gradientPosition({ ...line, style: 'angle' }, -10, 0)).toBeCloseTo(0.5)
    expect(gradientPosition({ ...line, style: 'angle' }, 0, 10)).toBeCloseTo(0.75)
  })

  it('lays a line over a box so the last colour reaches its far corners', () => {
    const box = { x: 0, y: 0, width: 100, height: 50 }
    expect(lineAcross('linear', box, 0)).toEqual({ style: 'linear', from: [0, 25], to: [100, 25] })
    const radial = lineAcross('radial', box, 0)
    expect(radial.from).toEqual([50, 25])
    expect(gradientPosition(radial, 100, 50)).toBeCloseTo(1)
    const diamond = lineAcross('diamond', box, 0)
    expect(diamond.to[0]).toBeCloseTo(125)
    expect(gradientPosition(diamond, 0, 0)).toBeCloseTo(1)
    const reflected = lineAcross('reflected', box, 90)
    expect(reflected.from).toEqual([50, 25])
    expect(reflected.to[1]).toBeCloseTo(50)
  })
})
