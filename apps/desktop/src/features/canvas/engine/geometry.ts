/*
 * 2D affine maths for layer placement. A `.comp` transform is the layer's unrotated box in document
 * pixels (`origin` its top-left corner, `size` its width and height), turned clockwise by `rotation`
 * degrees around the box's centre, with optional flips.
 */

import type { LayerTransform, Vec2 } from '../../../../shared/canvas/comp-format.ts'
import type { Rect } from './raster.ts'

/** `x' = a·x + c·y + e`, `y' = b·x + d·y + f`, the same order as the canvas 2D API. */
export interface Mat {
  a: number
  b: number
  c: number
  d: number
  e: number
  f: number
}

export const IDENTITY: Mat = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }

/** `m · n`: apply `n` first, then `m`. */
export const multiply = (m: Mat, n: Mat): Mat => ({
  a: m.a * n.a + m.c * n.b,
  b: m.b * n.a + m.d * n.b,
  c: m.a * n.c + m.c * n.d,
  d: m.b * n.c + m.d * n.d,
  e: m.a * n.e + m.c * n.f + m.e,
  f: m.b * n.e + m.d * n.f + m.f
})

export function invert(m: Mat): Mat {
  const det = m.a * m.d - m.b * m.c

  if (!det) {
    return { a: 0, b: 0, c: 0, d: 0, e: 0, f: 0 }
  }

  return {
    a: m.d / det,
    b: -m.b / det,
    c: -m.c / det,
    d: m.a / det,
    e: (m.c * m.f - m.d * m.e) / det,
    f: (m.b * m.e - m.a * m.f) / det
  }
}

export const apply = (m: Mat, [x, y]: Vec2): Vec2 => [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f]

export const translate = (x: number, y: number): Mat => ({ a: 1, b: 0, c: 0, d: 1, e: x, f: y })
export const scale = (x: number, y = x): Mat => ({ a: x, b: 0, c: 0, d: y, e: 0, f: 0 })

/** Clockwise in a y-down space. */
export function rotate(degrees: number): Mat {
  const r = ((degrees % 360) * Math.PI) / 180
  const cos = Math.cos(r)
  const sin = Math.sin(r)

  return { a: cos, b: sin, c: -sin, d: cos, e: 0, f: 0 }
}

export const centreOf = (t: LayerTransform): Vec2 => [t.origin[0] + t.size[0] / 2, t.origin[1] + t.size[1] / 2]

/** The unit square (0..1 both ways, before flips) to document pixels. */
export function unitToDocument(t: LayerTransform): Mat {
  const [cx, cy] = centreOf(t)

  return multiply(
    multiply(translate(cx, cy), rotate(t.rotation)),
    multiply(scale(t.size[0] * (t.flipX ? -1 : 1), t.size[1] * (t.flipY ? -1 : 1)), translate(-0.5, -0.5))
  )
}

/** A raster's pixels (0..width, 0..height) to document pixels. */
export const pixelToDocument = (t: LayerTransform, width: number, height: number): Mat => multiply(unitToDocument(t), scale(1 / width, 1 / height))

/** The four corners in document pixels: top-left, top-right, bottom-right, bottom-left of the layer. */
export function corners(t: LayerTransform): [Vec2, Vec2, Vec2, Vec2] {
  const m = unitToDocument(t)

  return [apply(m, [0, 0]), apply(m, [1, 0]), apply(m, [1, 1]), apply(m, [0, 1])]
}

/** The axis-aligned box around a placed layer, in document pixels. */
export function boundsOf(t: LayerTransform): Rect {
  const points = corners(t)
  const xs = points.map((p) => p[0])
  const ys = points.map((p) => p[1])
  const x = Math.min(...xs)
  const y = Math.min(...ys)

  return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y }
}

/** Does a document point fall on the placed layer's box? */
export function containsPoint(t: LayerTransform, point: Vec2): boolean {
  const [u, v] = apply(invert(unitToDocument(t)), point)

  return u >= 0 && u <= 1 && v >= 0 && v <= 1
}

/** Is this transform a plain placement at whole pixels and 1:1 scale (no resampling needed)? */
export function isPixelAligned(t: LayerTransform, width: number, height: number): boolean {
  const turn = ((t.rotation % 360) + 360) % 360

  return turn === 0 && !t.flipX && !t.flipY && t.size[0] === width && t.size[1] === height && Number.isInteger(t.origin[0]) && Number.isInteger(t.origin[1])
}

/** The same transform moved by a document offset. */
export const moved = (t: LayerTransform, dx: number, dy: number): LayerTransform => ({ ...t, origin: [t.origin[0] + dx, t.origin[1] + dy] })

/** Whole pixels and whole degrees, what dragging and rotating leave behind. */
export const rounded = (t: LayerTransform): LayerTransform => ({
  ...t,
  origin: [Math.round(t.origin[0]), Math.round(t.origin[1])],
  size: [Math.max(1, Math.round(t.size[0])), Math.max(1, Math.round(t.size[1]))],
  rotation: Math.round(t.rotation)
})

/** A column-major 3×3 for GLSL `mat3`. */
export const toMat3 = (m: Mat): Float32Array => new Float32Array([m.a, m.b, 0, m.c, m.d, 0, m.e, m.f, 1])
