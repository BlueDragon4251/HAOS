/*
 * Adjustment layers on the GPU. An adjustment changes the composite below it: every pixel's colour
 * goes through the adjustment, blends with the original in the layer's mode, and mixes back in by
 * the layer's coverage (its opacity, its own mask over its box, its folders' masks and its clipping
 * base). Alpha stays as it was, so an adjustment over transparency shows nothing.
 */

import { curvesTables, levelsTables, pcg, resolved } from '../adjust-math.ts'
import type { CanvasLayer } from '../document.ts'
import { invert, toMat3, unitToDocument } from '../geometry.ts'
import type { Compositor, FrameInfo, LayerCoverage, LayerPass } from './compositor.ts'
import type { Scaled } from './filters.ts'
import type { Program, Target } from './gl.ts'
import { ADJUST_FRAGMENT, SHADER_KIND } from './adjust-shaders.ts'
import { blendModeIndex, FULL_VERTEX } from './shaders.ts'

export class AdjustmentPass implements LayerPass {
  private readonly program: Program
  private tables: WebGLTexture | null = null
  private tablesKey = ''

  constructor(private readonly compositor: Compositor) {
    this.program = compositor.gpu.program(FULL_VERTEX, ADJUST_FRAGMENT)
  }

  draw(layer: CanvasLayer, backdrop: Target, into: Target, frame: FrameInfo, coverage: LayerCoverage): boolean {
    const adjustment = layer.adjustment

    if (!adjustment) {
      return false
    }

    const { gpu, filters, blank } = this.compositor
    const settings = resolved(adjustment)
    const format = frame.precise ? 'precise' : 'bytes'
    let source: Scaled | null = null

    if (adjustment.kind === 'Gaussian Blur') {
      source = filters.blur(backdrop, settings.blurRadius * frame.scale, format)
    } else if (adjustment.kind === 'Motion Blur') {
      source = filters.motion(backdrop, settings.motionAngle, settings.motionDistance * frame.scale, format)
    }

    gpu.bindTarget(into, frame.width, frame.height, false)
    const program = this.program
      .use()
      .texture('u_backdrop', 0, backdrop.texture)
      .texture('u_source', 4, source?.target.texture ?? blank)
      .vec2('u_sourceSize', source?.size[0] ?? 1, source?.size[1] ?? 1)
      .float('u_sourceOffset', source?.offset ?? 0)
      .texture('u_tables', 5, adjustment.kind === 'Levels' || adjustment.kind === 'Curves' ? this.tablesFor(adjustment) : blank)
      .int('u_kind', SHADER_KIND[adjustment.kind])
      .int('u_mode', blendModeIndex(layer.blendMode))
      .vec2('u_size', frame.width, frame.height)
      .float('u_scale', frame.scale)
      .vec2('u_docOffset', 0, 0)
      .float('u_opacity', coverage.opacity)

    if (source) {
      gpu.setSampling(source.target.texture, 'linear')
    }

    this.setCoverage(program, layer, coverage)
    this.setSettings(program, adjustment.kind, settings, adjustment)
    gpu.drawQuad()

    if (source?.owned) {
      this.compositor.release(source.target)
    }

    return true
  }

  /** The layer's own mask over its box (or the box it was unlinked at), its folders' masks and its clipping base. */
  private setCoverage(program: Program, layer: CanvasLayer, coverage: LayerCoverage): void {
    const { blank, textures, gpu } = this.compositor
    const mask = layer.mask && layer.maskEnabled !== false ? layer.mask : null

    if (mask) {
      const texture = textures.get(mask)
      gpu.setSampling(texture, 'linear')
      const placement = layer.maskLinked === false && layer.maskPlacement ? layer.maskPlacement : layer.transform
      program.texture('u_mask', 1, texture).int('u_maskMode', 2).mat3('u_docToMask', toMat3(invert(unitToDocument(placement))))
    } else {
      program.texture('u_mask', 1, blank).int('u_maskMode', 0)
    }

    program
      .texture('u_folderMask', 2, coverage.folderMask?.texture ?? blank)
      .int('u_hasFolderMask', Boolean(coverage.folderMask))
      .texture('u_clip', 3, coverage.clip?.texture ?? blank)
      .int('u_hasClip', Boolean(coverage.clip))
  }

  private setSettings(program: Program, kind: string, settings: ReturnType<typeof resolved>, adjustment: NonNullable<CanvasLayer['adjustment']>): void {
    switch (kind) {
      case 'Hue/Saturation':
        program.float('u_hue', adjustment.hue).float('u_saturation', adjustment.saturation).float('u_lightness', adjustment.lightness).int('u_colorize', adjustment.colorize)
        break
      case 'Exposure':
        program.float('u_exposureScale', 2 ** settings.exposure.exposure).float('u_offset', settings.exposure.offset).float('u_gamma', settings.exposure.gamma)
        break
      case 'Gradient Map': {
        const { shadows, highlights, reversed } = settings.gradientMap
        const [dark, light] = reversed ? [highlights, shadows] : [shadows, highlights]
        program.vec3('u_dark', dark.red, dark.green, dark.blue).vec3('u_light', light.red, light.green, light.blue)
        break
      }
      case 'Grain':
        program
          .float('u_amount', settings.grain.amount)
          .float('u_grainSize', settings.grain.size)
          .float('u_roughness', settings.grain.roughness)
          .uint('u_seed', settings.grain.seed)
          .uint('u_fineSeed', pcg((settings.grain.seed ^ 0x5bd1e995) >>> 0))
        break
      case 'Black & White': {
        const bw = settings.blackWhite
        program
          .floats('u_weights', [bw.reds, bw.yellows, bw.greens, bw.cyans, bw.blues, bw.magentas])
          .int('u_tint', bw.tint)
          .float('u_tintHue', bw.tintHue)
          .float('u_tintSaturation', bw.tintSaturation)
        break
      }
      case 'Color Balance': {
        const cb = settings.colorBalance
        program
          .vec3('u_shadows', cb.shadowCyanRed / 100, cb.shadowMagentaGreen / 100, cb.shadowYellowBlue / 100)
          .vec3('u_mids', cb.midCyanRed / 100, cb.midMagentaGreen / 100, cb.midYellowBlue / 100)
          .vec3('u_highlights', cb.highlightCyanRed / 100, cb.highlightMagentaGreen / 100, cb.highlightYellowBlue / 100)
          .int('u_preserve', cb.preserveLuminosity)
        break
      }
      case 'Add Noise':
        program.float('u_amount', settings.noise.amount).int('u_gaussian', settings.noise.gaussian).int('u_monochromatic', settings.noise.monochromatic).uint('u_seed', settings.noise.seed)
        break
    }
  }

  /** Levels or Curves as lookup tables on the GPU, made again only when the settings change. */
  private tablesFor(adjustment: NonNullable<CanvasLayer['adjustment']>): WebGLTexture {
    const key = adjustment.kind === 'Levels' ? `L${JSON.stringify(adjustment.levels)}` : `C${JSON.stringify(adjustment.curves)}`

    if (!this.tables || key !== this.tablesKey) {
      const data = adjustment.kind === 'Levels' ? levelsTables(adjustment.levels) : curvesTables(adjustment.curves)
      this.tables = this.compositor.gpu.floatTexture(256, 4, data, this.tables)
      this.tablesKey = key
    }

    return this.tables
  }

  dispose(): void {
    if (this.tables) {
      this.compositor.gpu.gl.deleteTexture(this.tables)
      this.tables = null
    }
  }
}
