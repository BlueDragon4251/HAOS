/*
 * The document on screen: re-composite when it changes, then draw the result with the view's zoom
 * and pan over the workspace, with a checkerboard under transparency. Smooth when zoomed out (with
 * mipmaps), crisp pixels when zoomed in.
 */

import type { CanvasDocument, CanvasLayer } from '../document.ts'
import { type Mat, multiply, scale, toMat3, translate } from '../geometry.ts'
import type { Raster, Rect } from '../raster.ts'
import { Compositor, type Rendered } from './compositor.ts'
import { Gpu, type Program } from './gl.ts'
import { DISPLAY_FRAGMENT, PLACE_VERTEX } from './shaders.ts'

/** Screen (CSS) pixels = document pixels × zoom + pan. */
export interface View {
  zoom: number
  panX: number
  panY: number
}

export interface Look {
  /** Around the page; null leaves it transparent so the window's glass shows. */
  workspace: [number, number, number] | null
  checkerLight: [number, number, number]
  checkerDark: [number, number, number]
}

export const MIN_ZOOM = 0.01
export const MAX_ZOOM = 64

/** Zoom to fit the document in a viewport, never past `maxZoom`. */
export function fitView(viewWidth: number, viewHeight: number, docWidth: number, docHeight: number, maxZoom = 1, margin = 32): View {
  const zoom = Math.max(MIN_ZOOM, Math.min(maxZoom, (viewWidth - margin * 2) / docWidth, (viewHeight - margin * 2) / docHeight))

  return { zoom, panX: (viewWidth - docWidth * zoom) / 2, panY: (viewHeight - docHeight * zoom) / 2 }
}

/** Zoom by a factor keeping the document point under (x, y) where it is. */
export function zoomAt(view: View, factor: number, x: number, y: number): View {
  const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.zoom * factor))
  const applied = zoom / view.zoom

  return { zoom, panX: x - (x - view.panX) * applied, panY: y - (y - view.panY) * applied }
}

/** Document pixels to screen pixels. */
export const docToScreen = (view: View): Mat => multiply(translate(view.panX, view.panY), scale(view.zoom))

export class ScreenRenderer {
  readonly gpu: Gpu
  readonly compositor: Compositor
  private readonly display: Program
  private rendered: Rendered | null = null
  private drawnKey = ''
  private drawnRevision = -1
  private drawnOverrides: ReadonlyMap<string, Partial<CanvasLayer>> | undefined
  private mipmapped = false

  constructor(readonly canvas: HTMLCanvasElement) {
    const gl = canvas.getContext('webgl2', { alpha: true, antialias: false, premultipliedAlpha: true, preserveDrawingBuffer: false, powerPreference: 'high-performance' })

    if (!gl) {
      throw new Error('Herald Canvas needs WebGL2, which this system does not provide')
    }

    this.gpu = new Gpu(gl)
    this.compositor = new Compositor(this.gpu)
    this.display = this.gpu.program(PLACE_VERTEX, DISPLAY_FRAGMENT)
  }

  /** Re-composite on the next draw even when the document says nothing changed. */
  invalidate(): void {
    this.drawnRevision = -1
  }

  /** The composite as the screen shows it, rendered again when the document (or what is hidden while editing) changed. */
  private current(doc: CanvasDocument, overrides?: ReadonlyMap<string, Partial<CanvasLayer>>): Rendered {
    if (!this.rendered || doc.key !== this.drawnKey || doc.revision !== this.drawnRevision || overrides !== this.drawnOverrides) {
      this.rendered = this.compositor.render(doc.state, { overrides })
      this.drawnKey = doc.key
      this.drawnRevision = doc.revision
      this.drawnOverrides = overrides
      this.mipmapped = false
    }

    return this.rendered
  }

  /** The composite's pixels over a document area (all of it by default), straight alpha; null when the GPU is gone. */
  read(doc: CanvasDocument, area?: Rect): Raster | null {
    if (this.gpu.gl.isContextLost()) {
      return null
    }

    const rendered = this.current(doc, this.drawnKey === doc.key ? this.drawnOverrides : undefined)
    const s = rendered.scale
    const box = area ? { x: Math.floor(area.x * s), y: Math.floor(area.y * s), width: Math.max(1, Math.round(area.width * s)), height: Math.max(1, Math.round(area.height * s)) } : undefined

    return this.compositor.read(rendered, null, box)
  }

  draw(doc: CanvasDocument | null, view: View, look: Look, dpr: number, overrides?: ReadonlyMap<string, Partial<CanvasLayer>>): void {
    const { gl } = this.gpu
    const { width, height } = this.canvas

    if (gl.isContextLost()) {
      return
    }

    this.gpu.bindTarget(null, width, height, false)

    if (look.workspace) {
      gl.clearColor(look.workspace[0], look.workspace[1], look.workspace[2], 1)
    } else {
      gl.clearColor(0, 0, 0, 0)
    }

    gl.clear(gl.COLOR_BUFFER_BIT)

    if (!doc) {
      return
    }

    const rendered = this.current(doc, overrides)
    // Device pixels per rendered pixel decides the filtering.
    const density = (view.zoom * dpr) / rendered.scale
    const sampling = density >= 2 ? 'nearest' : density < 1 ? 'mipmap' : 'linear'

    if (sampling === 'mipmap' && !this.mipmapped) {
      this.gpu.bindScratch(rendered.target.texture)
      gl.generateMipmap(gl.TEXTURE_2D)
      this.mipmapped = true
    }

    this.gpu.setSampling(rendered.target.texture, sampling)
    this.gpu.bindTarget(null, width, height, false)
    this.gpu.blendOver(false)

    // Unit square → document → screen (CSS) → device pixels, with y flipped for the default framebuffer.
    const flip: Mat = { a: 1, b: 0, c: 0, d: -1, e: 0, f: height }
    const place = multiply(flip, multiply(scale(dpr), multiply(docToScreen(view), scale(doc.state.width, doc.state.height))))
    this.display
      .use()
      .mat3('u_place', toMat3(place))
      .vec2('u_size', width, height)
      .texture('u_image', 0, rendered.target.texture)
      .float('u_checker', 8 * dpr)
      .vec3('u_light', ...look.checkerLight)
      .vec3('u_dark', ...look.checkerDark)
    this.gpu.drawQuad()
  }

  /** Free the GPU memory; the context itself goes with its canvas (a remount may reuse it). */
  dispose(): void {
    this.compositor.dispose()
  }
}
