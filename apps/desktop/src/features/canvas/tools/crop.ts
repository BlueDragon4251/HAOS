/*
 * The Crop tool: a box over the canvas (all of it at first) with handles to size it; drag outside
 * it for a new box, inside to move it. Enter crops the canvas to it, the way Canvas Size does:
 * layers keep their pixels. Escape lets it go.
 */

import { atom } from 'nanostores'
import type { LayerTransform, Vec2 } from '../../../../shared/canvas/comp-format.ts'
import { cropCanvas } from '../engine/canvas-size.ts'
import type { CanvasDocument } from '../engine/document.ts'
import type { View } from '../engine/gpu/view.ts'
import type { Rect } from '../engine/raster.ts'
import { dragFrame, handleCursor, hitFrame, quadOf } from '../engine/transform.ts'
import { drawFrame } from './transform.ts'
import { redraw, type ToolHandler } from './types.ts'

export const $crop = atom<{ docKey: string; rect: Rect } | null>(null)

const REACH = 6

const fullCanvas = (doc: CanvasDocument): Rect => ({ x: 0, y: 0, width: doc.state.width, height: doc.state.height })

/** The crop box on a document: the one being set, or the whole canvas. */
export const cropRect = (doc: CanvasDocument): Rect => {
  const crop = $crop.get()

  return crop?.docKey === doc.key ? crop.rect : fullCanvas(doc)
}

const asFrame = (rect: Rect): LayerTransform => ({ origin: [rect.x, rect.y], size: [rect.width, rect.height], rotation: 0, flipX: false, flipY: false, sampling: 'High quality' })

/** A frame as a box on whole pixels, whichever way it was dragged. */
function asRect(frame: LayerTransform): Rect {
  const [x0, y0] = frame.origin
  const x1 = x0 + frame.size[0]
  const y1 = y0 + frame.size[1]
  const x = Math.round(Math.min(x0, x1))
  const y = Math.round(Math.min(y0, y1))

  return { x, y, width: Math.max(1, Math.round(Math.max(x0, x1)) - x), height: Math.max(1, Math.round(Math.max(y0, y1)) - y) }
}

function setCrop(doc: CanvasDocument, rect: Rect): void {
  $crop.set({ docKey: doc.key, rect })
  redraw()
}

/** Crop the canvas to the box. */
export function applyCrop(doc: CanvasDocument): void {
  const rect = cropRect(doc)
  $crop.set(null)
  redraw()
  const full = fullCanvas(doc)

  if (rect.x !== full.x || rect.y !== full.y || rect.width !== full.width || rect.height !== full.height) {
    doc.commit('Crop', cropCanvas(doc.state, rect))
  }
}

export function cancelCrop(): void {
  $crop.set(null)
  redraw()
}

export const cropTool: ToolHandler = {
  cursor(doc, at) {
    if (!at) {
      return 'crosshair'
    }

    const frame = asFrame(cropRect(doc))
    const hit = hitFrame(frame, [at.x, at.y], REACH / at.view.zoom, 0)

    return !hit ? 'crosshair' : hit === 'move' ? 'move' : hit === 'rotate' ? 'crosshair' : handleCursor(frame, hit)
  },

  down(doc, at) {
    const frame = asFrame(cropRect(doc))
    const start: Vec2 = [at.x, at.y]
    const hit = hitFrame(frame, start, REACH / at.view.zoom, 0)

    if (hit && hit !== 'rotate') {
      return {
        move: (now) => setCrop(doc, asRect(dragFrame(frame, hit, start, [now.x, now.y], { constrain: now.shift, fromCentre: now.alt }))),
        up: () => {}
      }
    }

    return {
      move: (now) => {
        const end: Vec2 = now.shift ? [start[0] + Math.sign(now.x - start[0]) * Math.max(Math.abs(now.x - start[0]), Math.abs(now.y - start[1])), start[1] + Math.sign(now.y - start[1]) * Math.max(Math.abs(now.x - start[0]), Math.abs(now.y - start[1]))] : [now.x, now.y]
        setCrop(doc, asRect({ ...frame, origin: start, size: [end[0] - start[0], end[1] - start[1]] }))
      },
      up: () => {}
    }
  },

  key(doc, event) {
    if (event.key === 'Enter') {
      applyCrop(doc)

      return true
    }

    if (event.key === 'Escape' && $crop.get()) {
      cancelCrop()

      return true
    }

    return false
  },

  overlay(context, doc, view: View) {
    const rect = cropRect(doc)
    const x = view.panX + rect.x * view.zoom
    const y = view.panY + rect.y * view.zoom
    const width = rect.width * view.zoom
    const height = rect.height * view.zoom
    const page = { x: view.panX, y: view.panY, width: doc.state.width * view.zoom, height: doc.state.height * view.zoom }
    context.save()
    // What the crop cuts away is shaded.
    context.fillStyle = 'rgba(0, 0, 0, 0.45)'
    context.beginPath()
    context.rect(Math.min(page.x, x) - 4000, Math.min(page.y, y) - 4000, Math.max(page.width, width) + 8000, Math.max(page.height, height) + 8000)
    context.rect(x, y, width, height)
    context.fill('evenodd')
    // Thirds, for composing.
    context.strokeStyle = 'rgba(255, 255, 255, 0.35)'
    context.lineWidth = 1
    context.beginPath()

    for (const t of [1 / 3, 2 / 3]) {
      context.moveTo(x + width * t, y)
      context.lineTo(x + width * t, y + height)
      context.moveTo(x, y + height * t)
      context.lineTo(x + width, y + height * t)
    }

    context.stroke()
    context.restore()
    drawFrame(context, quadOf(asFrame(rect)), view, true, '#fff')
  },

  release() {
    cancelCrop()
  }
}
