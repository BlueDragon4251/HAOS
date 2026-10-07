import { describe, expect, it } from 'vitest'
import { decodePng, encodePng, pngSize } from './png.ts'

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
