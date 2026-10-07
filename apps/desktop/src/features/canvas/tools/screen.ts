/*
 * The composite the viewport already has on the GPU, for tools that look at all layers at once
 * (the eyedropper, the magic wand, the bucket with "all layers"). Without a viewport the document
 * is flattened offscreen instead.
 */

import type { CanvasDocument } from '../engine/document.ts'
import type { ScreenRenderer } from '../engine/gpu/view.ts'
import { flatten } from '../engine/project.ts'
import type { Raster } from '../engine/raster.ts'

let screen: ScreenRenderer | null = null

export function registerScreen(renderer: ScreenRenderer | null): void {
  screen = renderer
}

/** Every visible layer together, document sized, straight alpha. */
export function compositeOf(doc: CanvasDocument): Raster {
  return screen?.read(doc) ?? flatten(doc.state)
}

/** The composite's colour at a document pixel (straight RGBA), or null outside the canvas. */
export function compositeAt(doc: CanvasDocument, x: number, y: number): [number, number, number, number] | null {
  const px = Math.floor(x)
  const py = Math.floor(y)

  if (px < 0 || py < 0 || px >= doc.state.width || py >= doc.state.height) {
    return null
  }

  const raster = screen?.read(doc, { x: px, y: py, width: 1, height: 1 }) ?? flatten(doc.state).crop({ x: px, y: py, width: 1, height: 1 })

  return [raster.data[0], raster.data[1], raster.data[2], raster.data[3]]
}
