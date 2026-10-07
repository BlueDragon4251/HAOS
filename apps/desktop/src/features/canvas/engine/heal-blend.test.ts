import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../../shared/canvas/comp-format.ts'
import { beforeEdit, copier, healStroke, type PixelReader } from './clone.ts'
import { pixelToDocument } from './geometry.ts'
import { heal, membrane } from './heal-blend.ts'
import { History } from './history.ts'
import { Stroke } from './paint.ts'
import { Raster } from './raster.ts'

const identity = (raster: Raster) => pixelToDocument(defaultTransform(raster.width, raster.height), raster.width, raster.height)
const pixel = (raster: Raster, x: number, y: number) => [...raster.data.subarray((y * raster.width + x) * raster.channels, (y * raster.width + x + 1) * raster.channels)]

/** A square inside a frame one pixel wide: the frame fixed, the square to solve for. */
function framed(width: number, height: number, edge: (x: number, y: number) => number) {
  const fixed = new Uint8Array(width * height)
  const inside = new Uint8Array(width * height)
  const known = new Float32Array(width * height)

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x
      const border = x === 0 || y === 0 || x === width - 1 || y === height - 1
      fixed[i] = border ? 1 : 0
      inside[i] = border ? 0 : 1
      known[i] = border ? edge(x, y) : 0
    }
  }

  return { fixed, inside, known }
}

describe('the membrane', () => {
  it('fills the inside with the smoothest surface meeting the edge', () => {
    // A ramp along the edge has the ramp itself as its harmonic fill.
    const { fixed, inside, known } = framed(48, 30, (x, y) => x * 2 + y)
    const [solved] = membrane([known], fixed, inside, 48, 30)

    for (const [x, y] of [[10, 10], [24, 15], [40, 20], [1, 28]]) {
      expect(Math.abs(solved[y * 48 + x] - (x * 2 + y))).toBeLessThan(0.75)
    }
  })

  it('settles to a flat value inside a flat edge', () => {
    const { fixed, inside, known } = framed(200, 140, () => 37)
    const [solved] = membrane([known], fixed, inside, 200, 140)
    expect(Math.max(...solved.map((value) => Math.abs(value - 37)))).toBeLessThan(0.05)
  })
})

describe('the healing blend', () => {
  // A textured copy (a checkerboard around 200) laid into a flat gray area of 100.
  const size = 24
  const destination = new Uint8ClampedArray(size * size * 4)
  const copy = new Uint8ClampedArray(size * size * 4)
  const cover = new Float32Array(size * size)

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = y * size + x
      destination.set([100, 100, 100, 255], i * 4)
      const texture = (x + y) % 2 ? 220 : 180
      copy.set([texture, texture, texture, 255], i * 4)
      cover[i] = x >= 4 && x < 20 && y >= 4 && y < 20 ? 1 : 0
    }
  }

  it('keeps the copy’s texture but takes on the colour around it', () => {
    const out = heal(destination, copy, cover, size, size)
    let sum = 0

    for (let y = 6; y < 18; y++) {
      for (let x = 6; x < 18; x++) {
        sum += out[(y * size + x) * 4]
      }
    }

    // The mean moves to the surroundings' gray, with the checkerboard's swing kept.
    expect(Math.abs(sum / 144 - 100)).toBeLessThan(6)
    expect(Math.abs(out[(12 * size + 12) * 4] - out[(12 * size + 13) * 4])).toBeGreaterThan(30)
    // Outside the stroke nothing changes.
    expect(out[(1 * size + 1) * 4]).toBe(100)
  })

  it('mixes by the cover, and lays the copy as it is with nothing around to match', () => {
    const half = Float32Array.from(cover, (value) => value / 2)
    const out = heal(destination, copy, half, size, size)
    const full = heal(destination, copy, cover, size, size)
    const i = (12 * size + 12) * 4
    expect(Math.abs(out[i] - (100 + (full[i] - 100) / 2))).toBeLessThanOrEqual(1)
    const everywhere = heal(destination, copy, new Float32Array(size * size).fill(1), size, size)
    expect([...everywhere.subarray(i, i + 4)]).toEqual([...copy.subarray(i, i + 4)])
  })
})

describe('cloning', () => {
  /** Black on the left half, a red square at (4, 4)–(8, 8), clear on the right. */
  const picture = () => {
    const raster = new Raster(32, 16)

    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        raster.data.set(x >= 4 && x < 8 && y >= 4 && y < 8 ? [255, 0, 0, 255] : [0, 0, 0, 255], (y * 32 + x) * 4)
      }
    }

    return raster
  }
  const hard = { size: 6, hardness: 1, opacity: 1, flow: 1, spacing: 0.1 }

  /** A stroke at a document point, copying from `offset` away (from `scene` when given). */
  const cloneAt = (raster: Raster, layout: ReturnType<typeof identity>, point: [number, number], offset: [number, number], scene: Raster | null = null, size = 6) => {
    let copy: PixelReader = (_x, _y, out) => out.fill(0)
    const stroke = new Stroke(raster, layout, { ...hard, size }, { colour: [0, 0, 0], erase: false, sample: (x, y, out) => copy(x, y, out) }, null)
    copy = copier(raster, layout, offset, scene, stroke.edit)
    stroke.to(point[0], point[1])
    stroke.end()

    return { stroke, copy }
  }

  it('copies whole pixels from a distance, as they were before the stroke', () => {
    const raster = picture()
    // The red square, sixteen pixels to the left, lands on the clear right half.
    const { stroke } = cloneAt(raster, identity(raster), [22, 6], [-16, 0])
    expect(pixel(raster, 22, 6)).toEqual([255, 0, 0, 255])
    expect(pixel(raster, 21, 5)).toEqual([255, 0, 0, 255])
    const history = new History()
    history.push(stroke.finish('Clone Stamp')!)
    history.undo()
    expect(pixel(raster, 22, 6)[3]).toBe(0)
    // A clear copy lays nothing: the square stays as it was.
    cloneAt(raster, identity(raster), [6, 6], [16, 0])
    expect(pixel(raster, 6, 6)).toEqual([255, 0, 0, 255])
  })

  it('reads the pixels before the edit even after it changed them', () => {
    const raster = picture()
    const stroke = new Stroke(raster, identity(raster), hard, { colour: [0, 255, 0], erase: false }, null)
    stroke.to(5, 5)
    stroke.end()
    expect(pixel(raster, 5, 5)).toEqual([0, 255, 0, 255])
    const read = beforeEdit(stroke.edit, raster)
    const out = new Uint8ClampedArray(4)
    read(5, 5, out)
    expect([...out]).toEqual([255, 0, 0, 255])
    read(-1, 5, out)
    expect(out[3]).toBe(0)
  })

  it('copies from every layer through a picture in document space', () => {
    const raster = new Raster(16, 16)
    // The layer sits at x = 16: its pixel 6 is document pixel 22, which copies document pixel 6.
    cloneAt(raster, pixelToDocument(defaultTransform(16, 16, 16, 0), 16, 16), [22, 6], [-16, 0], picture())
    expect(pixel(raster, 6, 6)).toEqual([255, 0, 0, 255])
  })

  it('heals a stroke into the colour around it', () => {
    // A gray layer with a darker band to copy; the copy is healed into the lighter gray.
    const raster = Raster.filled(64, 32, [160, 160, 160, 255])

    for (let y = 0; y < 32; y++) {
      for (let x = 0; x < 16; x++) {
        const shade = 60 + ((x + y) % 2) * 20
        raster.data.set([shade, shade, shade, 255], (y * 64 + x) * 4)
      }
    }

    const { stroke, copy } = cloneAt(raster, identity(raster), [48, 16], [-40, 0], null, 10)
    // Cloned, the dark texture sits in the light gray; healed, it takes the gray's level.
    expect(pixel(raster, 48, 16)[0]).toBeLessThan(90)
    healStroke(stroke, copy)
    const centre = pixel(raster, 48, 16)[0]
    const beside = pixel(raster, 49, 16)[0]
    expect(Math.abs((centre + beside) / 2 - 160)).toBeLessThan(12)
    expect(Math.abs(centre - beside)).toBeGreaterThan(10)
    expect(pixel(raster, 60, 2)).toEqual([160, 160, 160, 255])
  })
})
