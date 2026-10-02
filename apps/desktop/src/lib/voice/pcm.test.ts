import { describe, expect, it } from 'vitest'
import { concatInt16, encodeWav, floatToInt16, FrameSlicer, int16ToBase64, int16ToFloat, resampleLinear, rms } from './pcm.ts'

describe('pcm conversions', () => {
  it('round-trips float and int16 within quantization error', () => {
    const floats = new Float32Array([0, 0.5, -0.5, 1, -1, 0.001])
    const back = int16ToFloat(floatToInt16(floats))

    for (let i = 0; i < floats.length; i++) {
      expect(Math.abs(back[i] - floats[i])).toBeLessThan(1 / 0x7fff + 1e-6)
    }
  })

  it('clamps out-of-range samples', () => {
    const out = floatToInt16(new Float32Array([2, -2]))
    expect(out[0]).toBe(0x7fff)
    expect(out[1]).toBe(-0x8000)
  })

  it('resamples 48k to 16k by a factor of three', () => {
    const input = new Float32Array(480).map((_, i) => Math.sin(i / 10))
    const out = resampleLinear(input, 48_000, 16_000)
    expect(out.length).toBe(160)
    expect(out[0]).toBe(input[0])
  })

  it('computes rms', () => {
    expect(rms(new Float32Array([0.5, -0.5, 0.5, -0.5]))).toBeCloseTo(0.5)
    expect(rms(new Float32Array(0))).toBe(0)
  })
})

describe('encodeWav', () => {
  it('writes a valid RIFF header for 16 kHz mono', () => {
    const wav = encodeWav(new Int16Array([1, -1, 2, -2]), 16_000)
    const view = new DataView(wav.buffer)
    expect(String.fromCharCode(...wav.subarray(0, 4))).toBe('RIFF')
    expect(String.fromCharCode(...wav.subarray(8, 12))).toBe('WAVE')
    expect(view.getUint32(24, true)).toBe(16_000)
    expect(view.getUint16(22, true)).toBe(1)
    expect(view.getUint32(40, true)).toBe(8)
    expect(wav.length).toBe(44 + 8)
  })
})

describe('int16ToBase64 and FrameSlicer', () => {
  it('encodes little-endian int16 as base64', () => {
    // 0x0102 little-endian is bytes 02 01; 0x0304 is 04 03.
    expect(int16ToBase64(new Int16Array([0x0102, 0x0304]))).toBe(Buffer.from([2, 1, 4, 3]).toString('base64'))
  })

  it('slices into fixed frames and carries the remainder', () => {
    const slicer = new FrameSlicer(4)
    expect(slicer.push(new Int16Array([1, 2, 3, 4, 5, 6])).map(f => Array.from(f))).toEqual([[1, 2, 3, 4]])
    expect(slicer.push(new Int16Array([7, 8, 9])).map(f => Array.from(f))).toEqual([[5, 6, 7, 8]])
    expect(Array.from(concatInt16([new Int16Array([1]), new Int16Array([2, 3])]))).toEqual([1, 2, 3])
  })
})
