/*
 * The Herald Canvas compositor: a document's layers drawn bottom to top on the GPU. Folders are
 * pass-through: they draw nothing themselves, and their opacity and mask multiply into every layer
 * inside them. A clipped layer is multiplied by its base's coverage (the base's pixels, opacity and
 * mask, but not its visibility or its folders). Normal layers go straight onto the backdrop through
 * the fixed blender; other modes are blended in a shader, ping-ponging between two targets.
 */

import { LIMITS } from '../../../../../shared/canvas/comp-format.ts'
import { ancestorsOf, type CanvasLayer, type DocState, findLayer, isShown } from '../document.ts'
import { invert, type Mat, multiply, scale as scaleMat, toMat3, unitToDocument } from '../geometry.ts'
import { Raster } from '../raster.ts'
import { Gpu, type Program, RasterTextures, type Sampling, type Target } from './gl.ts'
import { BLEND_FRAGMENT, blendModeIndex, COPY_FRAGMENT, COVERAGE_FRAGMENT, FULL_VERTEX, LAYER_FRAGMENT, PLACE_VERTEX } from './shaders.ts'

export interface RenderOptions {
  /** Target pixels per document pixel: below 1 for previews and thumbnails. */
  scale?: number
  /** Draw only these layers. */
  only?: ReadonlySet<string>
  /** Changes to layers for this render only (a merge drawing a layer at full opacity). */
  overrides?: ReadonlyMap<string, Partial<CanvasLayer>>
  /** Ignore enclosing folders: their visibility, opacity and masks. */
  isolated?: boolean
  /** Draw hidden layers too. */
  includeHidden?: boolean
}

export interface Rendered {
  target: Target
  /** The size drawn, which the scale and the GPU's largest texture decide. */
  width: number
  height: number
  scale: number
}

/** Where a render is drawing: its size, and document pixels to target pixels. */
export interface FrameInfo {
  width: number
  height: number
  scale: number
  docToTarget: Mat
}

/** Draws a layer kind the base compositor does not (adjustments, effects) into the bound target. */
export interface LayerPass {
  /** Draw `layer` over `backdrop` into the bound target; false when this pass does not handle it. */
  draw(layer: CanvasLayer, backdrop: Target, frame: FrameInfo, coverage: { opacity: number; folderMask: Target | null; clip: Target | null }): boolean
}

interface FrameState extends FrameInfo {
  folders: Map<string, Target>
  clips: Map<string, Target | null>
  borrowed: Target[]
}

const PRECISE_PIXELS = 16_777_216

export class Compositor {
  readonly textures: RasterTextures
  private targets: { a: Target; b: Target; source: Target; width: number; height: number } | null = null
  private pool: Target[] = []
  private readonly white: WebGLTexture
  private readonly layerProgram: Program
  private readonly coverageProgram: Program
  private readonly blendProgram: Program
  private readonly copyProgram: Program
  /** Adjustment layers and layer effects plug in here. */
  readonly passes: LayerPass[] = []

  constructor(readonly gpu: Gpu) {
    const { gl } = gpu
    this.textures = new RasterTextures(gpu)
    this.white = gl.createTexture()!
    gpu.bindScratch(this.white)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([255, 255, 255, 255]))
    gpu.setSampling(this.white, 'nearest')
    this.layerProgram = gpu.program(PLACE_VERTEX, LAYER_FRAGMENT)
    this.coverageProgram = gpu.program(PLACE_VERTEX, COVERAGE_FRAGMENT)
    this.blendProgram = gpu.program(FULL_VERTEX, BLEND_FRAGMENT)
    this.copyProgram = gpu.program(FULL_VERTEX, COPY_FRAGMENT)
  }

  /** A 1×1 white texture, bound to samplers a draw does not use. */
  get blank(): WebGLTexture {
    return this.white
  }

  private ensure(width: number, height: number) {
    if (this.targets?.width === width && this.targets.height === height) {
      return this.targets
    }

    this.disposeTargets()
    const precise = width * height <= PRECISE_PIXELS
    this.targets = {
      a: this.gpu.createTarget(width, height, { mipmaps: true, precise }),
      b: this.gpu.createTarget(width, height, { mipmaps: true, precise }),
      source: this.gpu.createTarget(width, height, { precise }),
      width,
      height
    }

    return this.targets
  }

  private borrow(frame: FrameState): Target {
    const target = this.pool.pop() ?? this.gpu.createTarget(frame.width, frame.height, { precise: false })
    frame.borrowed.push(target)

    return target
  }

  /** Composite the document; the result stays valid until the next render. */
  render(state: DocState, options: RenderOptions = {}): Rendered {
    const limit = this.gpu.maxTextureSize
    const scale = Math.min(options.scale ?? 1, limit / state.width, limit / state.height)
    const width = Math.max(1, Math.round(state.width * scale))
    const height = Math.max(1, Math.round(state.height * scale))
    const targets = this.ensure(width, height)
    const frame: FrameState = { width, height, scale, docToTarget: scaleMat(scale), folders: new Map(), clips: new Map(), borrowed: [] }
    const overrides = options.overrides
    const view: DocState = overrides?.size ? { ...state, layers: state.layers.map((layer) => (overrides.has(layer.id) ? { ...layer, ...overrides.get(layer.id) } : layer)) } : state
    let current = targets.a
    let other = targets.b

    this.textures.beginFrame()
    this.gpu.blendOver(false)
    this.gpu.bindTarget(current, width, height)

    for (const layer of view.layers) {
      if (layer.isGroup || (options.only && !options.only.has(layer.id))) {
        continue
      }

      if (!options.includeHidden && !(options.isolated ? layer.isVisible : isShown(view, layer))) {
        continue
      }

      if (!layer.pixels && !layer.adjustment && !layer.effects) {
        continue
      }

      const folders = options.isolated ? [] : ancestorsOf(view, layer)
      const opacity = (layer.opacity ?? 1) * folders.reduce((product, folder) => product * (folder.opacity ?? 1), 1)

      if (opacity <= 0) {
        continue
      }

      const folderMask = this.folderCoverage(folders, frame)
      const clip = layer.maskSourceID ? this.clipCoverage(view, layer.maskSourceID, frame, new Set([layer.id])) : null

      if (this.passes.length && (layer.adjustment || layer.effects)) {
        this.gpu.bindTarget(other, width, height, false)

        if (this.passes.some((pass) => pass.draw(layer, current, frame, { opacity, folderMask, clip }))) {
          ;[current, other] = [other, current]
          continue
        }
      }

      if (!layer.pixels) {
        continue
      }

      const mode = blendModeIndex(layer.blendMode)

      if (mode === 0) {
        this.gpu.bindTarget(current, width, height, false)
        this.gpu.blendOver(true)
        this.drawLayer(this.layerProgram, layer, frame, opacity, folderMask, clip)
        this.gpu.blendOver(false)
      } else {
        this.gpu.bindTarget(targets.source, width, height)
        this.drawLayer(this.layerProgram, layer, frame, opacity, folderMask, clip)
        this.blend(current, targets.source, other, mode, frame)
        ;[current, other] = [other, current]
      }
    }

    this.pool.push(...frame.borrowed)
    this.textures.sweep()

    return { target: current, width, height, scale }
  }

  /** Blend `source` over `backdrop` with a mode (0 is Normal) into `into`. */
  blend(backdrop: Target, source: Target, into: Target, mode: number, frame: FrameInfo): void {
    this.gpu.bindTarget(into, frame.width, frame.height, false)
    this.blendProgram.use().texture('u_backdrop', 0, backdrop.texture).texture('u_source', 1, source.texture).int('u_mode', mode).vec2('u_size', frame.width, frame.height)
    this.gpu.drawQuad()
  }

  /** Set the uniforms every placed draw shares, and draw the layer's quad. */
  drawLayer(program: Program, layer: CanvasLayer, frame: FrameInfo, opacity: number, folderMask: Target | null, clip: Target | null): void {
    const place = multiply(frame.docToTarget, unitToDocument(layer.transform))
    program.use().mat3('u_place', toMat3(place)).vec2('u_size', frame.width, frame.height).float('u_scale', frame.scale).vec2('u_docOffset', 0, 0).float('u_opacity', opacity)

    if (layer.pixels) {
      const onTarget = (Math.abs(layer.transform.size[0]) * frame.scale) / layer.pixels.width
      const sampling: Sampling = layer.transform.sampling === 'Nearest' ? 'nearest' : layer.transform.sampling === 'Smooth' || onTarget >= 1 ? 'linear' : 'mipmap'
      const texture = this.textures.get(layer.pixels, sampling === 'mipmap')
      this.gpu.setSampling(texture, sampling)
      program.texture('u_image', 0, texture).int('u_hasImage', true)
    } else {
      program.texture('u_image', 0, this.white).int('u_hasImage', false)
    }

    const mask = layer.mask && layer.maskEnabled !== false ? layer.mask : null

    if (mask) {
      const texture = this.textures.get(mask)
      this.gpu.setSampling(texture, 'linear')
      const placement = layer.maskLinked === false ? layer.maskPlacement : undefined
      program.texture('u_mask', 1, texture).int('u_maskMode', placement ? 2 : 1)

      if (placement) {
        program.mat3('u_docToMask', toMat3(invert(unitToDocument(placement))))
      }
    } else {
      program.texture('u_mask', 1, this.white).int('u_maskMode', 0)
    }

    program.texture('u_folderMask', 2, folderMask?.texture ?? this.white).int('u_hasFolderMask', Boolean(folderMask))
    program.texture('u_clip', 3, clip?.texture ?? this.white).int('u_hasClip', Boolean(clip))
    this.gpu.drawQuad()
  }

  /** The enclosing folders' enabled masks multiplied together, or null when none has one. */
  private folderCoverage(folders: CanvasLayer[], frame: FrameState): Target | null {
    let coverage: Target | null = null

    // Outermost first: each folder's coverage includes the folders around it.
    for (const folder of [...folders].reverse()) {
      if (!folder.mask || folder.maskEnabled === false) {
        continue
      }

      const known = frame.folders.get(folder.id)

      if (known) {
        coverage = known
        continue
      }

      const target = this.borrow(frame)
      const placement = folder.maskLinked === false && folder.maskPlacement ? folder.maskPlacement : folder.transform
      this.gpu.bindTarget(target, frame.width, frame.height)
      this.drawLayer(this.coverageProgram, { ...folder, pixels: null, transform: placement, maskLinked: true, maskPlacement: undefined }, frame, 1, coverage, null)
      frame.folders.set(folder.id, target)
      coverage = target
    }

    return coverage
  }

  /** A clipping base's coverage: its pixels' alpha, opacity, mask and its own base's coverage. */
  private clipCoverage(state: DocState, baseId: string, frame: FrameState, visiting: Set<string>): Target | null {
    if (frame.clips.has(baseId)) {
      return frame.clips.get(baseId)!
    }

    const base = findLayer(state, baseId)

    if (!base || base.isGroup || visiting.has(baseId) || visiting.size > LIMITS.clipChain) {
      return null
    }

    visiting.add(baseId)
    const upstream = base.maskSourceID ? this.clipCoverage(state, base.maskSourceID, frame, visiting) : null
    const target = this.borrow(frame)
    this.gpu.bindTarget(target, frame.width, frame.height)

    if (base.pixels || base.adjustment) {
      this.drawLayer(this.coverageProgram, base, frame, base.opacity ?? 1, null, upstream)
    }

    frame.clips.set(baseId, target)

    return target
  }

  /** Copy a texture into the bound target as it is, or unpremultiplied over a background. */
  copy(texture: WebGLTexture, options: { unpremultiply?: boolean; background?: [number, number, number] | null; sampling?: Sampling } = {}): void {
    this.gpu.setSampling(texture, options.sampling ?? 'nearest')
    const [r, g, b] = options.background ?? [0, 0, 0]
    this.copyProgram
      .use()
      .texture('u_source', 0, texture)
      .int('u_unpremultiply', Boolean(options.unpremultiply))
      .vec4('u_background', r, g, b, options.background ? 1 : 0)
    this.gpu.drawQuad()
  }

  /** A render's pixels: straight alpha, rows from the top; a background fills transparency (for JPEG). */
  read(rendered: Rendered, background: [number, number, number] | null = null): Raster {
    const { width, height } = rendered
    const target = this.gpu.createTarget(width, height, { precise: false })

    try {
      this.gpu.bindTarget(target, width, height)
      this.copy(rendered.target.texture, { unpremultiply: true, background })

      return new Raster(width, height, 4, this.gpu.readPixels(target))
    } finally {
      this.gpu.deleteTarget(target)
    }
  }

  private disposeTargets(): void {
    if (this.targets) {
      this.gpu.deleteTarget(this.targets.a)
      this.gpu.deleteTarget(this.targets.b)
      this.gpu.deleteTarget(this.targets.source)
      this.targets = null
    }

    this.pool.forEach((target) => this.gpu.deleteTarget(target))
    this.pool = []
  }

  dispose(): void {
    this.disposeTargets()
    this.textures.clear()
    this.gpu.gl.deleteTexture(this.white)
  }
}

/** A WebGL2 context of its own, for exports and previews made without a window on screen. */
export function headlessCompositor(): Compositor {
  const canvas = new OffscreenCanvas(1, 1)
  const gl = canvas.getContext('webgl2', { premultipliedAlpha: true, antialias: false, preserveDrawingBuffer: false })

  if (!gl) {
    throw new Error('Herald Canvas needs WebGL2, which this system does not provide')
  }

  return new Compositor(new Gpu(gl))
}
