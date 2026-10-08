import { parseHex } from '../../../../shared/theme.ts'
import type { CanvasLayer, DocState } from '../../canvas/engine/document.ts'
import { flatten } from '../../canvas/engine/project.ts'
import type { Raster } from '../../canvas/engine/raster.ts'
import { postScriptName, textStyle } from '../../canvas/engine/text.ts'
import { makeShapeLayer, makeTextLayer } from '../../canvas/text-layers.ts'
import { type Deck, type Slide, SLIDE_SIZE, type SlideElement } from './deck.ts'

/*
 * A slide drawn with the Herald Canvas engine: each element becomes a Canvas layer built at the
 * size the slide is shown (text laid out at that size, so it is sharp at any zoom and on any
 * screen), composited on the GPU over the slide's background. Nothing is kept between frames but
 * what the caller keeps.
 */

const rgb = (hex: string) => {
  const value = parseHex(hex) ?? { r: 0, g: 0, b: 0 }

  return { red: value.r / 255, green: value.g / 255, blue: value.b / 255 }
}

const ALIGN = { left: 'Left', center: 'Center', right: 'Right' } as const

async function layerFor(element: SlideElement, deck: Deck, scale: number): Promise<CanvasLayer | null> {
  const box = { x: element.x * scale, y: element.y * scale, width: Math.max(1, element.width * scale), height: Math.max(1, element.height * scale) }

  if (element.kind === 'shape') {
    return makeShapeLayer({ kind: element.shape === 'ellipse' ? 'Ellipse' : 'Rectangle', cornerRadius: element.radius * scale, ...rgb(element.fill) }, box, element.id)
  }

  if (!element.text.trim()) {
    return null
  }

  const fontName = postScriptName({ family: deck.theme.font, weight: element.bold ? 700 : 400, italic: element.italic })
  const style = textStyle({ content: element.text, fontName, fontSize: element.size * scale, alignment: ALIGN[element.align], boxSize: [box.width, box.height], ...rgb(element.color) })

  return makeTextLayer(style, [box.x, box.y], { from: 'top', name: element.id })
}

export interface RenderOptions {
  /** Leave one element out (the text box being typed into). */
  without?: string | null
}

/** The slide at `scale` (pixels a point) as straight-alpha pixels. */
export async function renderSlide(deck: Deck, slide: Slide, scale: number, options: RenderOptions = {}): Promise<Raster> {
  const width = Math.max(1, Math.round(SLIDE_SIZE.width * scale))
  const height = Math.max(1, Math.round(SLIDE_SIZE.height * scale))
  const layers = (await Promise.all(slide.elements.filter((element) => element.id !== options.without).map((element) => layerFor(element, deck, scale)))).filter((layer): layer is CanvasLayer => layer !== null)
  const state: DocState = { width, height, resolution: 72, layers, activeLayerId: null, guides: [], selection: null }
  const background = rgb(slide.background || deck.theme.background)

  return flatten(state, 1, [background.red, background.green, background.blue])
}

/** Put a rendered slide on a 2D canvas the size of the raster. */
export function paint(canvas: HTMLCanvasElement | OffscreenCanvas, raster: Raster): void {
  if (canvas.width !== raster.width || canvas.height !== raster.height) {
    canvas.width = raster.width
    canvas.height = raster.height
  }

  const context = canvas.getContext('2d') as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null
  context?.putImageData(new ImageData(raster.data as Uint8ClampedArray<ArrayBuffer>, raster.width, raster.height), 0, 0)
}

/** A slide as a PNG data URL, for print views. */
export async function slidePng(deck: Deck, slide: Slide, scale: number): Promise<string> {
  const raster = await renderSlide(deck, slide, scale)
  const canvas = new OffscreenCanvas(raster.width, raster.height)
  paint(canvas, raster)
  const blob = await canvas.convertToBlob({ type: 'image/png' })

  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}
