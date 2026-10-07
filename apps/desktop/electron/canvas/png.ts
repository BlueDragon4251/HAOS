import zlib from 'node:zlib'

/*
 * PNG for Herald Canvas projects: layers are 8-bit RGBA and masks 8-bit grayscale, exactly as the
 * format asks (a browser canvas can only write RGBA, and may drop alpha from opaque images). The
 * decoder covers what this encoder writes plus the common 8-bit kinds; anything else is decoded by
 * the renderer, which reads every PNG Chromium does.
 */

const SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)

  for (let n = 0; n < 256; n++) {
    let c = n

    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    }

    table[n] = c >>> 0
  }

  return table
})()

function crc32(buffers: Buffer[]): number {
  let crc = 0xffffffff

  for (const buffer of buffers) {
    for (let i = 0; i < buffer.length; i++) {
      crc = CRC_TABLE[(crc ^ buffer[i]) & 0xff] ^ (crc >>> 8)
    }
  }

  return (crc ^ 0xffffffff) >>> 0
}

function chunk(type: string, data: Buffer): Buffer {
  const head = Buffer.alloc(8)
  head.writeUInt32BE(data.length, 0)
  head.write(type, 4, 'ascii')
  const tail = Buffer.alloc(4)
  tail.writeUInt32BE(crc32([head.subarray(4), data]), 0)

  return Buffer.concat([head, data, tail])
}

const paeth = (a: number, b: number, c: number) => {
  const p = a + b - c
  const pa = Math.abs(p - a)
  const pb = Math.abs(p - b)
  const pc = Math.abs(p - c)

  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c
}

/**
 * Filtered scanlines. Each row takes the filter that leaves the smallest absolute sum (the usual
 * heuristic); large images use Paeth throughout, which is nearly as small at a fifth of the work.
 */
function filterRows(data: ArrayLike<number>, width: number, height: number, channels: number): Buffer {
  const stride = width * channels
  const out = Buffer.alloc((stride + 1) * height)
  const candidates = Array.from({ length: 5 }, () => Buffer.alloc(stride))
  const adaptive = stride * height <= 4_000_000

  for (let y = 0; y < height; y++) {
    const row = y * stride
    const prior = row - stride
    let best = adaptive ? 0 : y === 0 ? 1 : 4
    let bestSum = Infinity

    for (let filter = 0; adaptive && filter < 5; filter++) {
      const line = candidates[filter]
      let sum = 0

      for (let i = 0; i < stride; i++) {
        const value = data[row + i]
        const left = i >= channels ? data[row + i - channels] : 0
        const up = y > 0 ? data[prior + i] : 0
        const upLeft = y > 0 && i >= channels ? data[prior + i - channels] : 0
        const predicted = filter === 0 ? 0 : filter === 1 ? left : filter === 2 ? up : filter === 3 ? (left + up) >> 1 : paeth(left, up, upLeft)
        const residual = (value - predicted) & 0xff
        line[i] = residual
        sum += residual < 128 ? residual : 256 - residual

        if (sum >= bestSum) {
          break
        }
      }

      if (sum < bestSum) {
        bestSum = sum
        best = filter
      }
    }

    out[y * (stride + 1)] = best
    // Recompute the winner in full: the loop above may have stopped early once it lost.
    const line = candidates[best]

    for (let i = 0; i < stride; i++) {
      const value = data[row + i]
      const left = i >= channels ? data[row + i - channels] : 0
      const up = y > 0 ? data[prior + i] : 0
      const upLeft = y > 0 && i >= channels ? data[prior + i - channels] : 0
      const predicted = best === 0 ? 0 : best === 1 ? left : best === 2 ? up : best === 3 ? (left + up) >> 1 : paeth(left, up, upLeft)
      line[i] = (value - predicted) & 0xff
    }

    line.copy(out, y * (stride + 1) + 1)
  }

  return out
}

export interface PngImage {
  width: number
  height: number
  /** 1 (grayscale), 2 (grayscale and alpha), 3 (RGB) or 4 (RGBA). */
  channels: 1 | 2 | 3 | 4
  data: Uint8Array
}

/** An 8-bit PNG: RGBA for 4 channels, grayscale for 1; `ppi` adds the resolution (pHYs). */
export function encodePng(image: { width: number; height: number; channels: 1 | 4; data: ArrayLike<number> }, ppi?: number): Buffer {
  const { width, height, channels, data } = image

  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || data.length !== width * height * channels) {
    throw new Error(`a ${width}×${height} PNG needs ${width * height * channels} bytes, got ${data.length}`)
  }

  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0)
  header.writeUInt32BE(height, 4)
  header[8] = 8
  header[9] = channels === 4 ? 6 : 0
  const chunks = [SIGNATURE, chunk('IHDR', header)]

  if (ppi && Number.isFinite(ppi) && ppi > 0) {
    const physical = Buffer.alloc(9)
    const perMetre = Math.round(ppi / 0.0254)
    physical.writeUInt32BE(perMetre, 0)
    physical.writeUInt32BE(perMetre, 4)
    physical[8] = 1
    chunks.push(chunk('pHYs', physical))
  }

  chunks.push(chunk('IDAT', zlib.deflateSync(filterRows(data, width, height, channels), { level: 6 })), chunk('IEND', Buffer.alloc(0)))

  return Buffer.concat(chunks)
}

/** Decoded pixels as RGBA (4) or one gray value a pixel (1, for masks: colour averaged, times alpha). */
export function toChannels(image: PngImage, channels: 1 | 4): Uint8Array {
  const { width, height, data } = image
  const from = image.channels

  if (from === channels) {
    return data
  }

  const count = width * height
  const out = new Uint8Array(count * channels)

  for (let i = 0; i < count; i++) {
    const s = i * from
    const gray = from < 3
    const r = data[s]
    const g = gray ? r : data[s + 1]
    const b = gray ? r : data[s + 2]
    const a = from === 2 ? data[s + 1] : from === 4 ? data[s + 3] : 255

    if (channels === 4) {
      out[i * 4] = r
      out[i * 4 + 1] = g
      out[i * 4 + 2] = b
      out[i * 4 + 3] = a
    } else {
      out[i] = Math.round((((r + g + b) / 3) * a) / 255)
    }
  }

  return out
}

/** Decode an 8-bit, non-interlaced PNG (grayscale, gray+alpha, RGB, RGBA or palette). */
export function decodePng(buffer: Uint8Array): PngImage {
  const bytes = Buffer.from(buffer.buffer, buffer.byteOffset, buffer.byteLength)

  if (bytes.length < 8 || !bytes.subarray(0, 8).equals(SIGNATURE)) {
    throw new Error('not a PNG')
  }

  let offset = 8
  let width = 0
  let height = 0
  let colorType = -1
  let palette: Buffer | null = null
  let transparency: Buffer | null = null
  const idat: Buffer[] = []

  while (offset + 8 <= bytes.length) {
    const length = bytes.readUInt32BE(offset)
    const type = bytes.toString('ascii', offset + 4, offset + 8)
    const data = bytes.subarray(offset + 8, offset + 8 + length)
    offset += 12 + length

    if (type === 'IHDR') {
      width = data.readUInt32BE(0)
      height = data.readUInt32BE(4)
      colorType = data[9]

      if (data[8] !== 8 || data[12] !== 0) {
        throw new Error('only 8-bit, non-interlaced PNGs decode here')
      }
    } else if (type === 'PLTE') {
      palette = data
    } else if (type === 'tRNS') {
      transparency = data
    } else if (type === 'IDAT') {
      idat.push(data)
    } else if (type === 'IEND') {
      break
    }
  }

  const sourceChannels = colorType === 0 ? 1 : colorType === 2 ? 3 : colorType === 3 ? 1 : colorType === 4 ? 2 : colorType === 6 ? 4 : 0

  if (!sourceChannels || !width || !height) {
    throw new Error('unsupported PNG')
  }

  const raw = zlib.inflateSync(Buffer.concat(idat))
  const stride = width * sourceChannels
  const pixels = new Uint8Array(stride * height)

  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)]
    const line = y * (stride + 1) + 1

    for (let i = 0; i < stride; i++) {
      const left = i >= sourceChannels ? pixels[y * stride + i - sourceChannels] : 0
      const up = y > 0 ? pixels[(y - 1) * stride + i] : 0
      const upLeft = y > 0 && i >= sourceChannels ? pixels[(y - 1) * stride + i - sourceChannels] : 0
      const predicted = filter === 0 ? 0 : filter === 1 ? left : filter === 2 ? up : filter === 3 ? (left + up) >> 1 : paeth(left, up, upLeft)
      pixels[y * stride + i] = (raw[line + i] + predicted) & 0xff
    }
  }

  if (colorType !== 3) {
    return { width, height, channels: sourceChannels as PngImage['channels'], data: pixels }
  }

  if (!palette) {
    throw new Error('palette PNG without a palette')
  }

  const rgba = new Uint8Array(width * height * 4)

  for (let i = 0; i < width * height; i++) {
    const index = pixels[i]
    rgba[i * 4] = palette[index * 3]
    rgba[i * 4 + 1] = palette[index * 3 + 1]
    rgba[i * 4 + 2] = palette[index * 3 + 2]
    rgba[i * 4 + 3] = transparency && index < transparency.length ? transparency[index] : 255
  }

  return { width, height, channels: 4, data: rgba }
}

/** Pixel size of a PNG from its header, without decoding it. */
export function pngSize(buffer: Uint8Array): { width: number; height: number } | null {
  const bytes = Buffer.from(buffer.buffer, buffer.byteOffset, buffer.byteLength)

  if (bytes.length < 24 || !bytes.subarray(0, 8).equals(SIGNATURE) || bytes.toString('ascii', 12, 16) !== 'IHDR') {
    return null
  }

  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) }
}
