import { describe, expect, it } from 'vitest'
import { extentOf, inpaint } from './patchmatch.ts'

type Paint = (x: number, y: number) => [number, number, number]

function picture(width: number, height: number, paint: Paint): Uint8ClampedArray {
  const out = new Uint8ClampedArray(width * height * 4)

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      out.set([...paint(x, y), 255], (y * width + x) * 4)
    }
  }

  return out
}

function square(width: number, height: number, box: { x: number; y: number; size: number }, value = 255): Uint8Array {
  const out = new Uint8Array(width * height)

  for (let y = box.y; y < box.y + box.size; y++) {
    for (let x = box.x; x < box.x + box.size; x++) {
      out[y * width + x] = value
    }
  }

  return out
}

/** Mean absolute error per channel inside the hole, against the picture the hole was cut from. */
function holeError(result: Uint8ClampedArray, truth: Uint8ClampedArray, hole: Uint8Array): number {
  let sum = 0
  let n = 0

  for (let i = 0; i < hole.length; i++) {
    if (hole[i]) {
      for (let c = 0; c < 3; c++) {
        sum += Math.abs(result[i * 4 + c] - truth[i * 4 + c])
      }

      n += 3
    }
  }

  return sum / n
}

/** The picture with something else (a red block) where the hole is, so a fill copying the hole would show it. */
function withRed(truth: Uint8ClampedArray, hole: Uint8Array): Uint8ClampedArray {
  const out = truth.slice()

  hole.forEach((value, i) => value && out.set([255, 0, 0, 255], i * 4))

  return out
}

describe('inpaint', () => {
  const W = 160
  const H = 160
  const hole = square(W, H, { x: 60, y: 60, size: 40 })

  it('continues stripes through the hole', () => {
    const truth = picture(W, H, (x) => (Math.floor(x / 8) % 2 ? [240, 240, 240] : [20, 20, 20]))
    const filled = inpaint(withRed(truth, hole), W, H, hole, { seed: 7 })
    expect(holeError(filled, truth, hole)).toBeLessThan(12)
  })

  it('fills a gentle gradient smoothly', () => {
    const truth = picture(W, H, (x, y) => [40 + x * 0.6, 60 + y * 0.5, 120])
    const filled = inpaint(withRed(truth, hole), W, H, hole, { seed: 7 })
    expect(holeError(filled, truth, hole)).toBeLessThan(8)
  })

  it('carries a checkerboard on', () => {
    const truth = picture(W, H, (x, y) => ((Math.floor(x / 10) + Math.floor(y / 10)) % 2 ? [230, 200, 40] : [30, 60, 160]))
    const filled = inpaint(withRed(truth, hole), W, H, hole, { seed: 7 })
    expect(holeError(filled, truth, hole)).toBeLessThan(20)
  })

  it('never copies from the hole, and only from the source region when given one', () => {
    const truth = picture(W, H, (x) => (x < W / 2 ? [20, 40, 220] : [30, 200, 60]))
    const middle = square(W, H, { x: 70, y: 60, size: 20 })
    const left = Uint8Array.from({ length: W * H }, (_, i) => (i % W < W / 2 - 20 ? 1 : 0))
    const filled = inpaint(withRed(truth, middle), W, H, middle, { seed: 3, source: left })

    for (let i = 0; i < middle.length; i++) {
      if (middle[i]) {
        // Blue, from the left half: never the red that was in the hole, never the green on the right.
        expect(filled[i * 4]).toBeLessThan(60)
        expect(filled[i * 4 + 2]).toBeGreaterThan(160)
      }
    }
  })

  it('leaves everything outside the hole as it was, and blends a soft edge', () => {
    const truth = picture(64, 64, (x, y) => [(x * 4) & 255, (y * 4) & 255, 90])
    const soft = square(64, 64, { x: 24, y: 24, size: 16 }, 128)
    const filled = inpaint(truth, 64, 64, soft, { seed: 1 })

    for (let i = 0; i < soft.length; i++) {
      if (!soft[i]) {
        expect([filled[i * 4], filled[i * 4 + 1], filled[i * 4 + 2], filled[i * 4 + 3]]).toEqual([truth[i * 4], truth[i * 4 + 1], truth[i * 4 + 2], truth[i * 4 + 3]])
      }
    }

    expect(extentOf(soft, 64, 64)).toEqual({ x: 24, y: 24, width: 16, height: 16 })
  })

  it('says when there is nothing to fill from', () => {
    const everything = new Uint8Array(32 * 32).fill(255)
    expect(() => inpaint(picture(32, 32, () => [0, 0, 0]), 32, 32, everything)).toThrow(/not enough of the picture/)
  })
})
