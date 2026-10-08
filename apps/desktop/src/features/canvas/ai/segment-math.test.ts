import { describe, expect, it } from 'vitest'
import { boxMean, featherValues, fitSide, guidedFilter, maskFromLogits, maskFromProbability, maskOptions, modelInput, normalise, remap, resamplePlanes, rgbPlanes } from './segment-math.ts'

const near = (values: ArrayLike<number>, expected: number[], tolerance = 1e-4) => expected.forEach((value, i) => expect(Math.abs(values[i] - value), `index ${i}`).toBeLessThan(tolerance))

describe('segmentation maths', () => {
  it('averages areas when shrinking and interpolates when growing', () => {
    near(resamplePlanes(Float32Array.from([0, 2, 4, 6]), 4, 1, 1, 2, 1), [1, 5])
    near(resamplePlanes(Float32Array.from([0, 3]), 2, 1, 1, 3, 1), [0, 1.5, 3])
    near(resamplePlanes(Float32Array.from([1, 1, 1, 1, 1, 1]), 3, 2, 1, 7, 5).slice(0, 3), [1, 1, 1])
  })

  it('lays see-through pixels over white and normalises a model input', () => {
    near(rgbPlanes([255, 0, 0, 255, 0, 0, 0, 0], 2, 1), [1, 1, 0, 1, 0, 1])
    const input = modelInput([255, 255, 255, 255], 1, 1, 2, 2, [0.5, 0.5, 0.5], [1, 1, 1])
    expect(input).toHaveLength(12)
    near(input, Array(12).fill(0.5))
  })

  it('moves the edge to the threshold, keeping the model edge at 0.5', () => {
    expect(remap(0.3, 0.5)).toBeCloseTo(0.3)
    expect(remap(0.3, 0.3)).toBeCloseTo(0.5)
    expect(remap(0.6, 0.3)).toBeCloseTo(1)
    expect(remap(0.1, 0.8)).toBe(0)
    near(normalise(Float32Array.from([2, 4, 6])), [0, 0.5, 1])
  })

  it('keeps a default for a setting given as undefined, as a command that leaves it out does', () => {
    expect(maskOptions({ threshold: undefined, feather: undefined, refine: true })).toEqual({ threshold: 0.5, feather: 0, refine: true })
    expect(maskOptions({ threshold: 0.3, refine: false })).toEqual({ threshold: 0.3, feather: 0, refine: false })
    expect(maskOptions()).toEqual({ threshold: 0.5, feather: 0, refine: true })
  })

  it('takes box means with the window cut at the edges', () => {
    near(boxMean(Float32Array.from([3, 0, 0, 0, 9]), 5, 1, 1), [1.5, 1, 0, 3, 4.5])
  })

  it('snaps a soft mask to the edge of its guide', () => {
    const width = 40
    const guide = Float32Array.from({ length: width * 4 }, (_, i) => (i % width < 20 ? 0.1 : 0.9))
    // A mask whose edge is a 10-pixel ramp; the picture's edge is sharp, at 20.
    const soft = Float32Array.from({ length: width * 4 }, (_, i) => Math.min(1, Math.max(0, ((i % width) - 15) / 10)))
    const out = guidedFilter(guide, soft, width, 4, 3, 1e-3)
    expect(out[17]).toBeLessThan(soft[17])
    expect(out[22]).toBeGreaterThan(soft[22])
    expect(out[5]).toBeLessThan(0.05)
    expect(out[35]).toBeGreaterThan(0.95)
  })

  it('carries a low-resolution answer up to the layer, refined or not, then thresholds and feathers it', () => {
    const probability = Float32Array.from({ length: 16 }, (_, i) => (i % 4 < 2 ? 0 : 1))
    const rgba = new Uint8ClampedArray(8 * 8 * 4).map((_, i) => (i % 4 === 3 ? 255 : Math.floor(i / 4) % 8 < 4 ? 20 : 230))
    const plain = maskFromProbability(probability, 4, 4, rgba, 8, 8, { threshold: 0.5, feather: 0, refine: false })
    expect(plain).toHaveLength(64)
    expect(plain[0]).toBe(0)
    expect(plain[7]).toBe(255)
    const refined = maskFromProbability(probability, 4, 4, rgba, 8, 8, { threshold: 0.5, feather: 0, refine: true })
    expect(refined[1]).toBeLessThan(40)
    expect(refined[6]).toBeGreaterThan(215)
    const feathered = featherValues(Uint8Array.from([0, 0, 0, 255, 255, 255]), 6, 1, 2)
    expect(feathered[2]).toBeGreaterThan(0)
    expect(feathered[3]).toBeLessThan(255)
  })

  it('turns logits into a mask with a soft edge where they cross 0', () => {
    const mask = maskFromLogits(Float32Array.from([-6, -2, 2, 6]), 4, 1, 8, 1)
    expect(mask[0]).toBe(0)
    expect(mask[7]).toBe(255)
    expect(mask[3]).toBeGreaterThan(0)
    expect(mask[4]).toBeLessThan(255)
    expect(fitSide(3000, 2000, 1024)).toEqual({ width: 1024, height: 683, scale: 1024 / 3000 })
    expect(fitSide(500, 400, 1024)).toEqual({ width: 500, height: 400, scale: 1 })
  })
})
