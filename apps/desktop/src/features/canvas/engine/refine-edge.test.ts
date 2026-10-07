import { describe, expect, it } from 'vitest'
import { colourAlpha, decontaminate, DEFAULT_REFINE, edgeBand, edgeBox, edgeDistance, globalRefinements, refineMatte, viewPixels } from './refine-edge.ts'

/** A picture `width` wide and `height` tall: red on the left, blue on the right, mixed over `soft` pixels from x = `at`. */
function twoColours(width: number, height: number, at: number, soft: number): { rgba: Uint8ClampedArray; truth: Float32Array } {
  const rgba = new Uint8ClampedArray(width * height * 4)
  const truth = new Float32Array(width * height)

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const t = Math.min(1, Math.max(0, (x + 0.5 - at) / soft))
      const i = y * width + x
      // Red is the foreground here: its share is the true coverage.
      truth[i] = 1 - t
      rgba.set([255 * (1 - t), 30, 255 * t, 255], i * 4)
    }
  }

  return { rgba, truth }
}

/** A hard matte: 1 left of `at`, 0 from it on. */
const hardMatte = (width: number, height: number, at: number): Float32Array => Float32Array.from({ length: width * height }, (_, i) => (i % width < at ? 1 : 0))

describe('the edge band', () => {
  it('measures the distance to the edge from both sides', () => {
    const distance = edgeDistance(hardMatte(10, 1, 5), 10, 1)
    expect([...distance]).toEqual([5, 4, 3, 2, 1, 1, 2, 3, 4, 5])
  })

  it('covers the radius around the edge and whatever the brush painted', () => {
    const distance = Float32Array.from([1, 2, 3, 5, 9])
    expect([...edgeBand(distance, null, 3)].map((value) => Math.round(value * 100) / 100)).toEqual([1, 1, 1, 0, 0])
    const painted = Uint8Array.from([0, 0, 0, 0, 255])
    expect(edgeBand(distance, null, 3, painted)[4]).toBe(1)
    // Smart radius narrows the band where the picture's edge is crisp.
    expect(edgeBand(distance, Float32Array.from([1, 1, 1, 1, 1]), 8)[2]).toBe(0)
  })

  it('finds the box around the edge, grown by a margin', () => {
    // The last selected pixel of each row (x 7) marks the step.
    expect(edgeBox(hardMatte(20, 10, 8), 20, 10, 2)).toEqual({ x: 5, y: 0, width: 5, height: 10 })
    expect(edgeBox(new Float32Array(100).fill(1), 10, 10, 2)).toBeNull()
  })
})

describe('refining from colour', () => {
  it('recovers the coverage of a soft edge a hard selection cut through', () => {
    const { rgba, truth } = twoColours(40, 8, 18, 4)
    const matte = hardMatte(40, 8, 20)
    const band = edgeBand(edgeDistance(matte, 40, 8), null, 6)
    const { alpha, confidence } = colourAlpha(rgba, matte, band, 40, 8, 10)

    for (const x of [18, 19, 20, 21]) {
      const i = 3 * 40 + x
      expect(confidence[i]).toBeGreaterThan(0.9)
      expect(Math.abs(alpha[i] - truth[i])).toBeLessThan(0.05)
    }
  })

  it('does it over the whole matte, leaving what is far from the edge alone', () => {
    const { rgba, truth } = twoColours(60, 10, 28, 4)
    const refined = refineMatte(hardMatte(60, 10, 30), rgba, 60, 10, { ...DEFAULT_REFINE, radius: 6, smartRadius: false })
    expect(refined[5 * 60 + 5]).toBe(1)
    expect(refined[5 * 60 + 55]).toBe(0)
    expect(Math.abs(refined[5 * 60 + 29] - truth[5 * 60 + 29])).toBeLessThan(0.12)
    expect(Math.abs(refined[5 * 60 + 30] - truth[5 * 60 + 30])).toBeLessThan(0.12)
  })
})

describe('global refinements', () => {
  const crossing = (matte: Float32Array, width: number, row = 0): number => {
    for (let x = 0; x < width - 1; x++) {
      const a = matte[row * width + x]
      const b = matte[row * width + x + 1]

      if (a >= 0.5 && b < 0.5) {
        return x + (a - 0.5) / (a - b) + 0.5
      }
    }

    return -1
  }

  it('feathers a hard edge, and contrast hardens it again', () => {
    const soft = globalRefinements(hardMatte(30, 1, 15), 30, 1, { ...DEFAULT_REFINE, feather: 6 })
    expect(soft[13]).toBeGreaterThan(0.6)
    expect(soft[13]).toBeLessThan(1)
    expect(soft[16]).toBeGreaterThan(0)
    const hard = globalRefinements(soft, 30, 1, { ...DEFAULT_REFINE, contrast: 100 })
    expect(hard[12]).toBe(1)
    expect(hard[17]).toBe(0)
  })

  it('shifts the edge out or in', () => {
    const matte = hardMatte(40, 1, 20)
    expect(crossing(globalRefinements(matte, 40, 1, { ...DEFAULT_REFINE, shiftEdge: 60 }), 40)).toBeGreaterThan(21)
    expect(crossing(globalRefinements(matte, 40, 1, { ...DEFAULT_REFINE, shiftEdge: -60 }), 40)).toBeLessThan(19)
  })

  it('smooths a one-pixel notch out of an edge', () => {
    const width = 20
    const matte = hardMatte(width, 9, 10)
    // A pixel bitten out of the edge on the middle row.
    matte[4 * width + 9] = 0
    const smoothed = globalRefinements(matte, width, 9, { ...DEFAULT_REFINE, smooth: 60 })
    expect(smoothed[4 * width + 9]).toBeGreaterThan(0.5)
  })
})

describe('output', () => {
  it('moves the colour of half-covered pixels towards the foreground nearby', () => {
    const { rgba } = twoColours(30, 4, 14, 2)
    const matte = Float32Array.from({ length: 120 }, (_, i) => (i % 30 < 14 ? 1 : i % 30 === 14 ? 0.5 : 0))
    const cleaned = decontaminate(rgba, matte, 30, 4, 1, 6)
    const i = (1 * 30 + 14) * 4
    expect(cleaned[i]).toBeGreaterThan(rgba[i])
    expect(cleaned[i + 2]).toBeLessThan(rgba[i + 2])
    // Fully covered and uncovered pixels keep their colour.
    expect(cleaned[(1 * 30 + 5) * 4 + 2]).toBe(rgba[(1 * 30 + 5) * 4 + 2])
  })

  it('shows the matte in each view', () => {
    const rgba = Uint8ClampedArray.from([100, 150, 200, 255, 100, 150, 200, 255])
    const matte = Float32Array.from([1, 0])
    expect([...viewPixels(rgba, matte, 'black')]).toEqual([100, 150, 200, 255, 0, 0, 0, 255])
    expect([...viewPixels(rgba, matte, 'white')]).toEqual([100, 150, 200, 255, 255, 255, 255, 255])
    expect([...viewPixels(rgba, matte, 'bw')]).toEqual([255, 255, 255, 255, 0, 0, 0, 255])
    // Unselected pixels are tinted red over half their colour; selected ones show as they are.
    const overlay = viewPixels(rgba, matte, 'overlay')
    expect([overlay[4], overlay[5], overlay[6]]).toEqual([185, 68, 90])
    expect([overlay[0], overlay[1], overlay[2]]).toEqual([100, 150, 200])
  })
})
