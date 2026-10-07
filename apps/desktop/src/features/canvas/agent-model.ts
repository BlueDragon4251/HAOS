/*
 * The pure half of Herald Canvas's commands: reading paths, finding layers, describing them for
 * Hermes and placing pictures. No window, no I/O, so it is tested directly.
 */

import { BLEND_MODES, type BlendMode, type ShapeKind, type TextAlignment, type Vec2 } from '../../../shared/canvas/comp-format.ts'
import { type Anchor, ANCHORS } from './engine/canvas-size.ts'
import { type CanvasLayer, childrenOf, type DocState, findLayer } from './engine/document.ts'
import { boundsOf } from './engine/geometry.ts'
import type { Rect } from './engine/raster.ts'
import { postScriptName } from './engine/text.ts'

/** A full path from what Hermes or the person typed (`~/…` works); trailing slashes go. */
export function resolvePath(input: string, home: string): string {
  let value = input.trim()

  if (value === '~' || value.startsWith('~/')) {
    if (!home) {
      throw new Error('The home folder is not known yet; give the full path')
    }

    value = `${home}${value.slice(1)}`
  }

  if (!value.startsWith('/')) {
    throw new Error(`Give the full path (starting with / or ~/): ${input}`)
  }

  return value.replace(/\/+/g, '/').replace(/\/\.(?=\/|$)/g, '').replace(/(.)\/$/, '$1')
}

/** A layer by id, or by name (the topmost of that name; a unique part of a name also works). */
export function findByRef(state: DocState, ref: unknown): CanvasLayer {
  const text = String(ref ?? '').trim()

  if (!text) {
    throw new Error('Say which layer: its id or its name')
  }

  const lower = text.toLowerCase()
  const byId = state.layers.find((layer) => layer.id.toLowerCase() === lower)

  if (byId) {
    return byId
  }

  const named = state.layers.filter((layer) => layer.name.toLowerCase() === lower)

  if (named.length) {
    return named[named.length - 1]
  }

  const partial = state.layers.filter((layer) => layer.name.toLowerCase().includes(lower))

  if (partial.length === 1) {
    return partial[0]
  }

  throw new Error(`${partial.length ? 'Several layers match' : 'No layer is called'} “${text}”. The layers: ${state.layers.map((layer) => layer.name).join(', ') || 'none'}`)
}

export type LayerKind = 'pixels' | 'folder' | 'adjustment' | 'text' | 'shape' | 'blank'

export const kindOf = (layer: CanvasLayer): LayerKind => (layer.isGroup ? 'folder' : layer.adjustment ? 'adjustment' : layer.text ? 'text' : layer.shape ? 'shape' : layer.pixels ? 'pixels' : 'blank')

const round = (value: number, places = 2): number => Math.round(value * 10 ** places) / 10 ** places

/** One layer the way Hermes reads it. */
export function describeLayer(state: DocState, layer: CanvasLayer): Record<string, unknown> {
  const { transform } = layer
  const box = boundsOf(transform)

  return {
    id: layer.id,
    name: layer.name,
    kind: kindOf(layer),
    ...(layer.parentID ? { folder: findLayer(state, layer.parentID)?.name ?? layer.parentID } : {}),
    visible: layer.isVisible,
    opacity: round(layer.opacity ?? 1),
    blend: layer.isGroup ? 'Pass Through' : (layer.blendMode ?? 'Normal'),
    x: round(transform.origin[0], 1),
    y: round(transform.origin[1], 1),
    width: round(transform.size[0], 1),
    height: round(transform.size[1], 1),
    ...(transform.rotation ? { rotation: transform.rotation, bounds: { x: round(box.x, 1), y: round(box.y, 1), width: round(box.width, 1), height: round(box.height, 1) } } : {}),
    ...(transform.flipX ? { flipX: true } : {}),
    ...(transform.flipY ? { flipY: true } : {}),
    ...(layer.pixels ? { pixels: `${layer.pixels.width}×${layer.pixels.height}` } : {}),
    ...(layer.maskSourceID ? { clippedTo: findLayer(state, layer.maskSourceID)?.name ?? layer.maskSourceID } : {}),
    ...(layer.mask ? { mask: layer.maskEnabled === false ? 'off' : 'on' } : {}),
    ...(layer.adjustment ? { adjustment: layer.adjustment.kind } : {}),
    ...(layer.text ? { text: layer.text.content, font: layer.text.fontName, size: layer.text.fontSize, align: layer.text.alignment.toLowerCase() } : {}),
    ...(layer.shape ? { shape: layer.shape.kind === 'Rectangle' && layer.shape.cornerRadius > 0 ? 'rounded rectangle' : layer.shape.kind.toLowerCase() } : {})
  }
}

/** The layers top to bottom, as the Layers panel lists them, with folders' contents after each folder. */
export function describeLayers(state: DocState): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  const visit = (parentID: string | undefined) => {
    const children = childrenOf(state, parentID)

    for (let i = children.length - 1; i >= 0; i--) {
      out.push(describeLayer(state, children[i]))

      if (children[i].isGroup) {
        visit(children[i].id)
      }
    }
  }
  visit(undefined)

  return out
}

export type Fit = 'contain' | 'cover' | 'none' | 'stretch'

export const finite = (value: unknown): number | undefined => (typeof value === 'number' && Number.isFinite(value) ? value : undefined)

/**
 * Where a picture of `width`×`height` goes on the canvas: an explicit box (a missing side keeps the
 * proportions), or fitted inside it (`contain`, the default, never enlarging), covering it, at its
 * own size, or stretched over it.
 */
export function placementOf(width: number, height: number, canvas: { width: number; height: number }, args: Record<string, unknown>): { x: number; y: number; width: number; height: number } {
  const x = finite(args.x)
  const y = finite(args.y)
  let w = finite(args.width)
  let h = finite(args.height)
  const fit = (typeof args.fit === 'string' ? args.fit : 'contain') as Fit

  if (w !== undefined || h !== undefined) {
    w ??= (h! * width) / height
    h ??= (w * height) / width
  } else if (fit === 'stretch') {
    w = canvas.width
    h = canvas.height
  } else if (fit === 'none') {
    w = width
    h = height
  } else {
    const scale = fit === 'cover' ? Math.max(canvas.width / width, canvas.height / height) : Math.min(1, canvas.width / width, canvas.height / height)
    w = width * scale
    h = height * scale
  }

  return { x: x ?? (canvas.width - w) / 2, y: y ?? (canvas.height - h) / 2, width: w, height: h }
}

/** A colour or gradient fill's box: what is given, and the rest of the canvas for what is not. */
export function fillBox(canvas: { width: number; height: number }, args: Record<string, unknown>): { x: number; y: number; width: number; height: number } {
  const x = finite(args.x) ?? 0
  const y = finite(args.y) ?? 0

  return { x, y, width: Math.max(1, Math.round(finite(args.width) ?? canvas.width - x)), height: Math.max(1, Math.round(finite(args.height) ?? canvas.height - y)) }
}

/** A blend mode however it was written ("soft light", "SoftLight", "Linear Dodge (Add)"). */
export function blendFrom(value: unknown): BlendMode | undefined {
  if (value === undefined || value === '') {
    return undefined
  }

  const squash = (text: string) => text.toLowerCase().replace(/[^a-z]/g, '')
  const wanted = String(value)
  const mode = BLEND_MODES.find((entry) => entry.toLowerCase() === wanted.toLowerCase() || squash(entry) === squash(wanted)) ?? (squash(wanted) === 'add' ? 'Linear Dodge (Add)' : undefined)

  if (!mode) {
    throw new Error(`Blend modes: ${BLEND_MODES.join(', ')}`)
  }

  return mode
}

/** Opacity from 0 to 1, or from a percentage. */
export function opacityFrom(value: unknown): number | undefined {
  const number = finite(value)

  return number === undefined ? undefined : Math.max(0, Math.min(1, number > 1 ? number / 100 : number))
}

const words = (value: unknown): string => String(value ?? '').trim().toLowerCase()

/** Text alignment however it was written ("centre", "middle", "right"); undefined when not given. */
export function alignFrom(value: unknown): TextAlignment | undefined {
  const text = words(value)

  if (!text) {
    return undefined
  }

  if (['left', 'start'].includes(text)) {
    return 'Left'
  }

  if (['center', 'centre', 'middle'].includes(text)) {
    return 'Center'
  }

  if (['right', 'end'].includes(text)) {
    return 'Right'
  }

  throw new Error('align is left, center or right')
}

/** A shape kind however it was written: a rectangle (rect, square, box), a rounded one, an ellipse (circle, oval) or a line. */
export function shapeKindFrom(value: unknown): { kind: ShapeKind; rounded: boolean } {
  const text = words(value).replace(/[\s_-]+/g, ' ')

  if (['rectangle', 'rect', 'square', 'box'].includes(text)) {
    return { kind: 'Rectangle', rounded: false }
  }

  if (['rounded', 'rounded rectangle', 'rounded rect', 'round rect', 'pill'].includes(text)) {
    return { kind: 'Rectangle', rounded: true }
  }

  if (['ellipse', 'circle', 'oval'].includes(text)) {
    return { kind: 'Ellipse', rounded: false }
  }

  if (['line', 'rule', 'stroke'].includes(text)) {
    return { kind: 'Line', rounded: false }
  }

  throw new Error('kind is rectangle, rounded, ellipse or line')
}

/** Style words at the end of a font name ("Avenir Next Bold Italic") and the weights they stand for. */
const FONT_STYLES: [RegExp, number][] = [
  [/^(thin|hairline)$/, 100],
  [/^(extra ?light|ultra ?light)$/, 200],
  [/^light$/, 300],
  [/^(regular|normal|book|plain)$/, 400],
  [/^medium$/, 500],
  [/^(semi ?bold|demi ?bold)$/, 600],
  [/^bold$/, 700],
  [/^(extra ?bold|ultra ?bold)$/, 800],
  [/^(black|heavy)$/, 900]
]

/**
 * A font as the format keeps it (a PostScript-style name) from what was written: a PostScript
 * name as it is ("HelveticaNeue-Bold"), or a family with style words after it ("Avenir Next
 * Bold Italic", "Georgia").
 */
export function fontNameFrom(value: unknown, fallback = 'Helvetica'): string {
  const text = String(value ?? '').trim()

  if (!text) {
    return fallback
  }

  if (!/\s/.test(text)) {
    return text
  }

  const parts = text.split(/\s+/)
  let weight = 400
  let italic = false

  // Style words come off the end ("Extra Bold" is two of them).
  for (;;) {
    const last = parts.at(-1)?.toLowerCase() ?? ''
    const two = parts.length > 2 ? `${parts.at(-2)!.toLowerCase()} ${last}` : ''
    const pair = FONT_STYLES.find(([pattern]) => two && pattern.test(two))
    const single = FONT_STYLES.find(([pattern]) => pattern.test(last))

    if (/^(italic|oblique)$/.test(last) && parts.length > 1) {
      italic = true
      parts.pop()
    } else if (pair) {
      weight = pair[1]
      parts.splice(-2, 2)
    } else if (single && parts.length > 1) {
      weight = single[1]
      parts.pop()
    } else {
      break
    }
  }

  return postScriptName({ family: parts.join(' '), weight, italic })
}

/** An anchor however it was written ("top left", "top-left", "centre", "bottom"); the centre when not given. */
export function anchorFrom(value: unknown): Anchor {
  const text = words(value).replace(/[\s_]+/g, '-').replace('centre', 'center').replace('middle', 'center')

  if (!text || text === 'center-center') {
    return 'center'
  }

  const flipped = text.split('-').reverse().join('-')
  const anchor = ANCHORS.find((entry) => entry === text || entry === flipped || entry === text.replace(/-?center-?/, ''))

  if (!anchor) {
    throw new Error(`anchor is one of: ${ANCHORS.join(', ')}`)
  }

  return anchor
}

export type ResizePlan = { kind: 'canvas'; width: number; height: number; anchor: Anchor } | { kind: 'image'; width: number; height: number; resample: boolean }

/**
 * What a resize asks for: with `scale`, or `image` true, the whole image scaled (one side alone
 * keeps the proportions); otherwise the canvas grown or cut around `anchor`, layers untouched.
 */
export function resizePlan(state: { width: number; height: number }, args: Record<string, unknown>): ResizePlan {
  const scale = finite(args.scale)
  const width = finite(args.width)
  const height = finite(args.height)

  if (scale !== undefined) {
    if (scale <= 0) {
      throw new Error('scale must be above 0')
    }

    return { kind: 'image', width: Math.max(1, Math.round(state.width * scale)), height: Math.max(1, Math.round(state.height * scale)), resample: args.resample !== false }
  }

  if (width === undefined && height === undefined) {
    throw new Error('Give width and height (pixels), or scale')
  }

  if (args.image === true) {
    const w = width ?? (height! * state.width) / state.height
    const h = height ?? (width! * state.height) / state.width

    return { kind: 'image', width: Math.max(1, Math.round(w)), height: Math.max(1, Math.round(h)), resample: args.resample !== false }
  }

  return { kind: 'canvas', width: Math.max(1, Math.round(width ?? state.width)), height: Math.max(1, Math.round(height ?? state.height)), anchor: anchorFrom(args.anchor) }
}

/** The box a crop keeps: what is given, the rest of the canvas for what is not, cut to the canvas. */
export function cropBox(state: { width: number; height: number }, args: Record<string, unknown>): Rect {
  const x = Math.max(0, Math.round(finite(args.x) ?? 0))
  const y = Math.max(0, Math.round(finite(args.y) ?? 0))
  const width = Math.min(state.width - x, Math.round(finite(args.width) ?? state.width - x))
  const height = Math.min(state.height - y, Math.round(finite(args.height) ?? state.height - y))

  if (width < 1 || height < 1) {
    throw new Error(`That box is outside the ${state.width}×${state.height} canvas`)
  }

  return { x, y, width, height }
}

/** A line's two ends from a box: it runs from (x, y) to (x + width, y + height). */
export function lineEnds(args: Record<string, unknown>, canvas: { width: number; height: number }): [Vec2, Vec2] {
  const x = finite(args.x) ?? 0
  const y = finite(args.y) ?? canvas.height / 2
  const width = finite(args.width) ?? canvas.width - x
  const height = finite(args.height) ?? 0

  if (!width && !height) {
    throw new Error('A line needs a length: give width (across) and/or height (down)')
  }

  return [
    [x, y],
    [x + width, y + height]
  ]
}

/** Settings over an adjustment's defaults: nested objects merge, the rest replaces. */
export function mergeSettings(base: Record<string, unknown>, extra: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base }

  for (const [key, value] of Object.entries(extra)) {
    const current = out[key]
    out[key] = value && typeof value === 'object' && !Array.isArray(value) && current && typeof current === 'object' && !Array.isArray(current) ? mergeSettings(current as Record<string, unknown>, value as Record<string, unknown>) : value
  }

  return out
}
