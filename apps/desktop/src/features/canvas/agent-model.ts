/*
 * The pure half of Herald Canvas's commands: reading paths, finding layers, describing them for
 * Hermes and placing pictures. No window, no I/O, so it is tested directly.
 */

import { BLEND_MODES, type BlendMode } from '../../../shared/canvas/comp-format.ts'
import { type CanvasLayer, childrenOf, type DocState, findLayer } from './engine/document.ts'
import { boundsOf } from './engine/geometry.ts'

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
    ...(layer.text ? { text: layer.text.content } : {})
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

/** Settings over an adjustment's defaults: nested objects merge, the rest replaces. */
export function mergeSettings(base: Record<string, unknown>, extra: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base }

  for (const [key, value] of Object.entries(extra)) {
    const current = out[key]
    out[key] = value && typeof value === 'object' && !Array.isArray(value) && current && typeof current === 'object' && !Array.isArray(current) ? mergeSettings(current as Record<string, unknown>, value as Record<string, unknown>) : value
  }

  return out
}
