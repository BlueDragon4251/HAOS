/*
 * Small WebGL2 helpers for Herald Canvas: programs with cached uniforms, render targets, and a
 * texture cache that uploads a raster once and afterwards only the part that changed.
 */

import type { Raster } from '../raster.ts'

export interface Target {
  texture: WebGLTexture
  framebuffer: WebGLFramebuffer
  width: number
  height: number
  /** Mipmap levels allocated (1 for none). */
  levels: number
}

export class Program {
  private readonly locations = new Map<string, WebGLUniformLocation | null>()

  constructor(
    private readonly gl: WebGL2RenderingContext,
    readonly handle: WebGLProgram
  ) {}

  private at(name: string): WebGLUniformLocation | null {
    if (!this.locations.has(name)) {
      this.locations.set(name, this.gl.getUniformLocation(this.handle, name))
    }

    return this.locations.get(name)!
  }

  use(): this {
    this.gl.useProgram(this.handle)

    return this
  }

  int(name: string, value: number | boolean): this {
    this.gl.uniform1i(this.at(name), Number(value))

    return this
  }

  float(name: string, value: number): this {
    this.gl.uniform1f(this.at(name), value)

    return this
  }

  vec2(name: string, x: number, y: number): this {
    this.gl.uniform2f(this.at(name), x, y)

    return this
  }

  vec3(name: string, x: number, y: number, z: number): this {
    this.gl.uniform3f(this.at(name), x, y, z)

    return this
  }

  vec4(name: string, x: number, y: number, z: number, w: number): this {
    this.gl.uniform4f(this.at(name), x, y, z, w)

    return this
  }

  mat3(name: string, value: Float32Array): this {
    this.gl.uniformMatrix3fv(this.at(name), false, value)

    return this
  }

  /** Bind a texture to a unit and point the sampler at it. */
  texture(name: string, unit: number, texture: WebGLTexture | null): this {
    this.gl.activeTexture(this.gl.TEXTURE0 + unit)
    this.gl.bindTexture(this.gl.TEXTURE_2D, texture)
    this.gl.uniform1i(this.at(name), unit)

    return this
  }
}

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type)!
  gl.shaderSource(shader, source)
  gl.compileShader(shader)

  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS) && !gl.isContextLost()) {
    const message = gl.getShaderInfoLog(shader)
    gl.deleteShader(shader)
    throw new Error(`Herald Canvas shader did not compile: ${message}`)
  }

  return shader
}

export type Sampling = 'linear' | 'nearest' | 'mipmap'

/** Uploads and texture settings happen on this unit, which no shader samples, so they never disturb a draw's bindings. */
const SCRATCH_UNIT = 15

export class Gpu {
  readonly maxTextureSize: number
  /** Can targets hold half floats (smoother blending), or only 8 bits? */
  readonly halfFloat: boolean
  private readonly quad: WebGLVertexArrayObject
  private readonly programs = new Map<string, Program>()

  constructor(readonly gl: WebGL2RenderingContext) {
    this.maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE)
    this.halfFloat = Boolean(gl.getExtension('EXT_color_buffer_float'))
    gl.getExtension('OES_texture_float_linear')

    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW)
    this.quad = gl.createVertexArray()!
    gl.bindVertexArray(this.quad)
    gl.enableVertexAttribArray(0)
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0)
    gl.bindVertexArray(null)
  }

  program(vertex: string, fragment: string): Program {
    const key = `${vertex}\n---\n${fragment}`
    let program = this.programs.get(key)

    if (!program) {
      const { gl } = this
      const handle = gl.createProgram()!
      gl.attachShader(handle, compile(gl, gl.VERTEX_SHADER, vertex))
      gl.attachShader(handle, compile(gl, gl.FRAGMENT_SHADER, fragment))
      gl.bindAttribLocation(handle, 0, 'a_unit')
      gl.linkProgram(handle)

      if (!gl.getProgramParameter(handle, gl.LINK_STATUS) && !gl.isContextLost()) {
        throw new Error(`Herald Canvas shaders did not link: ${gl.getProgramInfoLog(handle)}`)
      }

      program = new Program(gl, handle)
      this.programs.set(key, program)
    }

    return program
  }

  drawQuad(): void {
    const { gl } = this
    gl.bindVertexArray(this.quad)
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
    gl.bindVertexArray(null)
  }

  /** Bind a texture to change or fill it, away from the units draws sample. */
  bindScratch(texture: WebGLTexture | null): void {
    const { gl } = this
    gl.activeTexture(gl.TEXTURE0 + SCRATCH_UNIT)
    gl.bindTexture(gl.TEXTURE_2D, texture)
  }

  setSampling(texture: WebGLTexture, sampling: Sampling): void {
    const { gl } = this
    this.bindScratch(texture)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, sampling === 'nearest' ? gl.NEAREST : sampling === 'mipmap' ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, sampling === 'nearest' ? gl.NEAREST : gl.LINEAR)
  }

  /** A texture to render into, transparent; `mipmaps` allocates levels for zoomed-out drawing. */
  createTarget(width: number, height: number, options: { mipmaps?: boolean; precise?: boolean } = {}): Target {
    const { gl } = this
    const levels = options.mipmaps ? Math.floor(Math.log2(Math.max(width, height))) + 1 : 1
    const texture = gl.createTexture()!
    this.bindScratch(texture)
    gl.texStorage2D(gl.TEXTURE_2D, levels, options.precise !== false && this.halfFloat ? gl.RGBA16F : gl.RGBA8, width, height)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    this.setSampling(texture, 'linear')

    const framebuffer = gl.createFramebuffer()!
    gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer)
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.bindFramebuffer(gl.FRAMEBUFFER, null)

    return { texture, framebuffer, width, height, levels }
  }

  deleteTarget(target: Target | null | undefined): void {
    if (target) {
      this.gl.deleteFramebuffer(target.framebuffer)
      this.gl.deleteTexture(target.texture)
    }
  }

  /** Draw into a target (or the screen when null), clearing it first unless told otherwise. */
  bindTarget(target: Target | null, width: number, height: number, clear = true): void {
    const { gl } = this
    gl.bindFramebuffer(gl.FRAMEBUFFER, target?.framebuffer ?? null)
    gl.viewport(0, 0, width, height)

    if (clear) {
      gl.clearColor(0, 0, 0, 0)
      gl.clear(gl.COLOR_BUFFER_BIT)
    }
  }

  /** Premultiplied source-over through the fixed blender (the fast path for Normal layers). */
  blendOver(on: boolean): void {
    const { gl } = this

    if (on) {
      gl.enable(gl.BLEND)
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
    } else {
      gl.disable(gl.BLEND)
    }
  }

  /** Read a target's pixels (RGBA, 8 bits, rows from the top). */
  readPixels(target: Target, x = 0, y = 0, width = target.width, height = target.height): Uint8ClampedArray {
    const { gl } = this
    const out = new Uint8ClampedArray(width * height * 4)
    gl.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer)
    gl.readPixels(x, y, width, height, gl.RGBA, gl.UNSIGNED_BYTE, out)
    gl.bindFramebuffer(gl.FRAMEBUFFER, null)

    return out
  }
}

interface Uploaded {
  texture: WebGLTexture
  version: number
  /** The size uploaded: smaller than the raster when it is past the GPU's largest texture. */
  width: number
  height: number
  mipmaps: boolean
  usedAt: number
}

/** Textures for rasters: RGBA premultiplied on the way up, masks as one channel. */
export class RasterTextures {
  private readonly entries = new Map<Raster, Uploaded>()
  private staging = new Uint8Array(0)
  private frame = 0

  constructor(private readonly gpu: Gpu) {}

  /** Start a frame: textures not used since the previous one can go at `sweep`. */
  beginFrame(): void {
    this.frame++
  }

  get(raster: Raster, mipmaps = false): WebGLTexture {
    const { gl } = this.gpu
    let entry = this.entries.get(raster)
    const tooBig = raster.width > this.gpu.maxTextureSize || raster.height > this.gpu.maxTextureSize

    if (entry && entry.mipmaps !== mipmaps) {
      gl.deleteTexture(entry.texture)
      this.entries.delete(raster)
      entry = undefined
    }

    if (!entry) {
      const ratio = tooBig ? this.gpu.maxTextureSize / Math.max(raster.width, raster.height) : 1
      const width = Math.max(1, Math.floor(raster.width * ratio))
      const height = Math.max(1, Math.floor(raster.height * ratio))
      const texture = gl.createTexture()!
      this.gpu.bindScratch(texture)
      const levels = mipmaps ? Math.floor(Math.log2(Math.max(width, height))) + 1 : 1
      gl.texStorage2D(gl.TEXTURE_2D, levels, raster.channels === 4 ? gl.RGBA8 : gl.R8, width, height)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
      this.gpu.setSampling(texture, mipmaps ? 'mipmap' : 'linear')
      entry = { texture, version: -1, width, height, mipmaps, usedAt: this.frame }
      this.entries.set(raster, entry)
    }

    entry.usedAt = this.frame

    if (entry.version !== raster.version) {
      this.upload(raster, entry)
      entry.version = raster.version
    }

    return entry.texture
  }

  private upload(raster: Raster, entry: Uploaded): void {
    const { gl } = this.gpu
    this.gpu.bindScratch(entry.texture)
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)

    if (entry.width !== raster.width || entry.height !== raster.height) {
      // Past the GPU's limit: a reduced copy until tiled drawing takes over.
      const reduced = new Uint8Array(entry.width * entry.height * raster.channels)

      for (let y = 0; y < entry.height; y++) {
        const sy = Math.floor((y * raster.height) / entry.height)

        for (let x = 0; x < entry.width; x++) {
          const sx = Math.floor((x * raster.width) / entry.width)
          const s = (sy * raster.width + sx) * raster.channels
          const d = (y * entry.width + x) * raster.channels

          for (let c = 0; c < raster.channels; c++) {
            reduced[d + c] = raster.data[s + c]
          }
        }
      }

      if (raster.channels === 4) {
        premultiplyInPlace(reduced)
      }

      gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, entry.width, entry.height, raster.channels === 4 ? gl.RGBA : gl.RED, gl.UNSIGNED_BYTE, reduced)
    } else {
      const rect = raster.changedSince(entry.version) ?? raster.bounds

      if (!rect.width || !rect.height) {
        return
      }

      if (raster.channels === 1) {
        gl.pixelStorei(gl.UNPACK_ROW_LENGTH, raster.width)
        gl.pixelStorei(gl.UNPACK_SKIP_PIXELS, rect.x)
        gl.pixelStorei(gl.UNPACK_SKIP_ROWS, rect.y)
        gl.texSubImage2D(gl.TEXTURE_2D, 0, rect.x, rect.y, rect.width, rect.height, gl.RED, gl.UNSIGNED_BYTE, raster.data)
        gl.pixelStorei(gl.UNPACK_ROW_LENGTH, 0)
        gl.pixelStorei(gl.UNPACK_SKIP_PIXELS, 0)
        gl.pixelStorei(gl.UNPACK_SKIP_ROWS, 0)
      } else {
        const size = rect.width * rect.height * 4

        if (this.staging.length < size) {
          this.staging = new Uint8Array(size)
        }

        const staging = this.staging.subarray(0, size)

        for (let row = 0; row < rect.height; row++) {
          const start = ((rect.y + row) * raster.width + rect.x) * 4
          staging.set(raster.data.subarray(start, start + rect.width * 4), row * rect.width * 4)
        }

        premultiplyInPlace(staging)
        gl.texSubImage2D(gl.TEXTURE_2D, 0, rect.x, rect.y, rect.width, rect.height, gl.RGBA, gl.UNSIGNED_BYTE, staging)
      }
    }

    if (entry.mipmaps) {
      this.gpu.bindScratch(entry.texture)
      gl.generateMipmap(gl.TEXTURE_2D)
    }
  }

  /** Free textures of rasters no frame has used lately. */
  sweep(keepFrames = 2): void {
    for (const [raster, entry] of this.entries) {
      if (this.frame - entry.usedAt >= keepFrames) {
        this.gpu.gl.deleteTexture(entry.texture)
        this.entries.delete(raster)
      }
    }
  }

  clear(): void {
    for (const entry of this.entries.values()) {
      this.gpu.gl.deleteTexture(entry.texture)
    }

    this.entries.clear()
  }
}

/** Straight to premultiplied alpha, rounding to nearest. */
export function premultiplyInPlace(data: Uint8Array | Uint8ClampedArray): void {
  for (let i = 0; i < data.length; i += 4) {
    const a = data[i + 3]

    if (a === 255) {
      continue
    }

    if (a === 0) {
      data[i] = data[i + 1] = data[i + 2] = 0
      continue
    }

    data[i] = (data[i] * a + 127) / 255
    data[i + 1] = (data[i + 1] * a + 127) / 255
    data[i + 2] = (data[i + 2] * a + 127) / 255
  }
}
