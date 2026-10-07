/*
 * Fills for Herald Canvas: finding the pixels like a clicked one (the paint bucket and the magic
 * wand), and laying a colour, a gradient or transparency into a layer's pixels with a strength for
 * each pixel (the selection, the found area and the tool's opacity together). Masks take gray.
 */

import type { Vec2 } from '../../../../shared/canvas/comp-format.ts'
import type { Mat } from './geometry.ts'
import { Raster, type Rect } from './raster.ts'

export type RGBA = [number, number, number, number]

/** How strongly a raster pixel takes the fill, 0 to 1. */
export type Strength = (px: number, py: number) => number

/** A colour as a mask value: its luminance. */
export const grayOf = (r: number, g: number, b: number): number => 0.299 * r + 0.587 * g + 0.114 * b

/**
 * Pixels like the one at (x, y): every channel within `tolerance` (0 to 255) of it, compared with
 * colour times alpha so all transparent pixels match each other. With `contiguous`, only those
 * joined to it (side by side). 255 marks them; null when (x, y) is outside the raster.
 */
export function similarPixels(source: Raster, x: number, y: number, tolerance: number, contiguous: boolean): Raster | null {
  const { width, height, channels, data } = source
  const sx = Math.floor(x)
  const sy = Math.floor(y)

  if (sx < 0 || sy < 0 || sx >= width || sy >= height) {
    return null
  }

  const seed = sy * width + sx
  const out = new Raster(width, height, 1)
  const marks = out.data
  let match: (i: number) => boolean

  if (channels === 1) {
    const value = data[seed]
    match = (i) => Math.abs(data[i] - value) <= tolerance
  } else {
    const a = data[seed * 4 + 3]
    const r = (data[seed * 4] * a) / 255
    const g = (data[seed * 4 + 1] * a) / 255
    const b = (data[seed * 4 + 2] * a) / 255
    match = (i) => {
      const o = i * 4
      const alpha = data[o + 3]

      return Math.abs(alpha - a) <= tolerance && Math.abs((data[o] * alpha) / 255 - r) <= tolerance && Math.abs((data[o + 1] * alpha) / 255 - g) <= tolerance && Math.abs((data[o + 2] * alpha) / 255 - b) <= tolerance
    }
  }

  if (!contiguous) {
    for (let i = 0; i < marks.length; i++) {
      if (match(i)) {
        marks[i] = 255
      }
    }

    return out
  }

  // Scanline flood fill: fill a run, then look for runs to fill above and below it.
  const stack = [sx, sy]

  while (stack.length) {
    const py = stack.pop()!
    const px = stack.pop()!
    const row = py * width

    if (marks[row + px] || !match(row + px)) {
      continue
    }

    let left = px
    let right = px

    while (left > 0 && !marks[row + left - 1] && match(row + left - 1)) {
      left--
    }

    while (right < width - 1 && !marks[row + right + 1] && match(row + right + 1)) {
      right++
    }

    marks.fill(255, row + left, row + right + 1)

    for (const ny of [py - 1, py + 1]) {
      if (ny < 0 || ny >= height) {
        continue
      }

      const next = ny * width
      let inRun = false

      for (let nx = left; nx <= right; nx++) {
        const fits = !marks[next + nx] && match(next + nx)

        if (fits && !inRun) {
          stack.push(nx, ny)
        }

        inRun = fits
      }
    }
  }

  return out
}

/** Lay colour over a raster pixel by `amount` (0 to 1): straight alpha over what is there, or towards gray on a mask. */
function lay(raster: Raster, index: number, r: number, g: number, b: number, a: number, amount: number): void {
  const { data } = raster

  if (raster.channels === 1) {
    const k = amount * (a / 255)
    data[index] = data[index] + (grayOf(r, g, b) - data[index]) * k

    return
  }

  const o = index * 4
  const sa = (a / 255) * amount

  if (sa <= 0) {
    return
  }

  const da = data[o + 3] / 255
  const outA = sa + da * (1 - sa)
  const keep = da * (1 - sa)
  data[o] = (r * sa + data[o] * keep) / outA
  data[o + 1] = (g * sa + data[o + 1] * keep) / outA
  data[o + 2] = (b * sa + data[o + 2] * keep) / outA
  data[o + 3] = outA * 255
}

/** Fill an area of a raster with one colour, each pixel by its strength. */
export function fillRaster(raster: Raster, area: Rect, colour: RGBA, strength: Strength): void {
  const [r, g, b, a] = colour

  for (let y = area.y; y < area.y + area.height; y++) {
    for (let x = area.x; x < area.x + area.width; x++) {
      const amount = strength(x, y)

      if (amount > 0) {
        lay(raster, y * raster.width + x, r, g, b, a, Math.min(1, amount))
      }
    }
  }

  raster.touch(area)
}

/** Take pixels away (alpha on a layer; hidden on a mask), each by its strength. */
export function eraseRaster(raster: Raster, area: Rect, strength: Strength): void {
  const { data, channels, width } = raster

  for (let y = area.y; y < area.y + area.height; y++) {
    for (let x = area.x; x < area.x + area.width; x++) {
      const amount = Math.min(1, strength(x, y))

      if (amount > 0) {
        const o = (y * width + x) * channels + (channels === 4 ? 3 : 0)
        data[o] = data[o] * (1 - amount)
      }
    }
  }

  raster.touch(area)
}

export interface GradientSpec {
  kind: 'linear' | 'radial'
  /** Document points: where the first colour is, and where the last one is reached. */
  from: Vec2
  to: Vec2
  start: RGBA
  end: RGBA
}

/** Where a document point falls along a gradient, 0 to 1. */
export function gradientPosition(spec: GradientSpec, x: number, y: number): number {
  const dx = spec.to[0] - spec.from[0]
  const dy = spec.to[1] - spec.from[1]
  const length = dx * dx + dy * dy

  if (!length) {
    return 1
  }

  const t = spec.kind === 'radial' ? Math.sqrt(((x - spec.from[0]) ** 2 + (y - spec.from[1]) ** 2) / length) : ((x - spec.from[0]) * dx + (y - spec.from[1]) * dy) / length

  return Math.max(0, Math.min(1, t))
}

/** A 4×4 ordered dither, so long gradients do not band. */
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((value) => (value + 0.5) / 16 - 0.5)

/** Lay a gradient into an area of a raster placed by `toDocument`, each pixel by its strength. */
export function paintGradient(raster: Raster, area: Rect, toDocument: Mat, spec: GradientSpec, strength: Strength): void {
  const { start, end } = spec
  // Mixed with colour times alpha, so a fade to transparency keeps its colour.
  const premultiplied = (colour: RGBA) => [(colour[0] * colour[3]) / 255, (colour[1] * colour[3]) / 255, (colour[2] * colour[3]) / 255, colour[3]]
  const from = premultiplied(start)
  const to = premultiplied(end)

  for (let y = area.y; y < area.y + area.height; y++) {
    for (let x = area.x; x < area.x + area.width; x++) {
      const amount = strength(x, y)

      if (amount <= 0) {
        continue
      }

      const dx = toDocument.a * (x + 0.5) + toDocument.c * (y + 0.5) + toDocument.e
      const dy = toDocument.b * (x + 0.5) + toDocument.d * (y + 0.5) + toDocument.f
      const t = gradientPosition(spec, dx, dy)
      const dither = BAYER[(y & 3) * 4 + (x & 3)]
      const a = Math.max(0, Math.min(255, from[3] + (to[3] - from[3]) * t + dither))
      const mix = (channel: number) => (a > 0 ? Math.max(0, Math.min(255, ((from[channel] + (to[channel] - from[channel]) * t) * 255) / Math.max(a, 1e-6) + dither)) : 0)
      lay(raster, y * raster.width + x, mix(0), mix(1), mix(2), a, Math.min(1, amount))
    }
  }

  raster.touch(area)
}
