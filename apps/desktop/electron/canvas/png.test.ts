import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { decodePng, encodePng, PngStream, pngSize } from './png.ts'

function noise(length: number, seed = 1): Uint8Array {
  const data = new Uint8Array(length)
  let state = seed

  for (let i = 0; i < length; i++) {
    state = (state * 1103515245 + 12345) >>> 0
    // Half smooth gradient, half noise, so every filter gets used.
    data[i] = i % 7 < 4 ? (i * 3) & 0xff : state >>> 24
  }

  return data
}

describe('encodePng', () => {
  it('round-trips RGBA layers exactly', () => {
    const image = { width: 37, height: 23, channels: 4 as const, data: noise(37 * 23 * 4) }
    const decoded = decodePng(encodePng(image))
    expect(decoded).toMatchObject({ width: 37, height: 23, channels: 4 })
    expect(Buffer.from(decoded.data).equals(Buffer.from(image.data))).toBe(true)
  })

  it('writes masks as 8-bit grayscale', () => {
    const image = { width: 16, height: 9, channels: 1 as const, data: noise(16 * 9, 7) }
    const bytes = encodePng(image)
    // IHDR colour type 0 is grayscale.
    expect(bytes[25]).toBe(0)
    expect(Buffer.from(decodePng(bytes).data).equals(Buffer.from(image.data))).toBe(true)
  })

  it('records the resolution and reads the size from the header', () => {
    const bytes = encodePng({ width: 4, height: 3, channels: 4, data: new Uint8Array(48) }, 300)
    expect(bytes.includes(Buffer.from('pHYs'))).toBe(true)
    expect(pngSize(bytes)).toEqual({ width: 4, height: 3 })
    expect(pngSize(new Uint8Array([1, 2, 3]))).toBeNull()
  })

  it('refuses pixel data of the wrong length', () => {
    expect(() => encodePng({ width: 2, height: 2, channels: 4, data: new Uint8Array(15) })).toThrow()
  })

  it('keeps large images exact with the single-pass filter', () => {
    const image = { width: 1200, height: 900, channels: 4 as const, data: noise(1200 * 900 * 4, 3) }
    expect(Buffer.from(decodePng(encodePng(image)).data).equals(Buffer.from(image.data))).toBe(true)
  })
})

describe('PngStream', () => {
  const written = async (image: { width: number; height: number; data: Uint8Array }, rows: number) => {
    const folder = await fs.mkdtemp(path.join(os.tmpdir(), 'herald-png-'))
    const file = path.join(folder, 'band.png')

    try {
      const stream = await PngStream.open(file, image.width, image.height, 4, 72)
      const stride = image.width * 4

      for (let y = 0; y < image.height; y += rows) {
        await stream.write(image.data.subarray(y * stride, Math.min(image.height, y + rows) * stride))
      }

      await stream.finish()

      return new Uint8Array(await fs.readFile(file))
    } finally {
      await fs.rm(folder, { recursive: true, force: true })
    }
  }

  it('writes a PNG a band of rows at a time that decodes to the same pixels', async () => {
    const small = { width: 41, height: 29, data: noise(41 * 29 * 4, 5) }
    const bytes = await written(small, 7)
    expect(Buffer.from(decodePng(bytes).data).equals(Buffer.from(small.data))).toBe(true)
    expect(Buffer.from(bytes).includes(Buffer.from('pHYs'))).toBe(true)
    // Large enough for the single-pass filter, across bands.
    const large = { width: 1200, height: 1000, data: noise(1200 * 1000 * 4, 9) }
    expect(Buffer.from(decodePng(await written(large, 333)).data).equals(Buffer.from(large.data))).toBe(true)
  })

  it('refuses rows that do not fit, and an end before every row is in', async () => {
    const folder = await fs.mkdtemp(path.join(os.tmpdir(), 'herald-png-'))

    try {
      const stream = await PngStream.open(path.join(folder, 'short.png'), 4, 4, 4)
      await expect(stream.write(new Uint8Array(15))).rejects.toThrow(/16 bytes each/)
      await stream.write(new Uint8Array(32))
      await expect(stream.finish()).rejects.toThrow(/2 of its 4 rows/)
      await stream.abort()
    } finally {
      await fs.rm(folder, { recursive: true, force: true })
    }
  })
})
