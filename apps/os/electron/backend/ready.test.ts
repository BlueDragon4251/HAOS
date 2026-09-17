import { describe, expect, it } from 'vitest'
import { LineBuffer, parseReadyLine } from './ready.ts'

describe('backend ready handshake', () => {
  it('parses both sentinel spellings and rejects noise', () => {
    expect(parseReadyLine('HERMES_BACKEND_READY port=62766')).toBe(62766)
    expect(parseReadyLine('HERMES_DASHBOARD_READY port=9119\r')).toBe(9119)
    expect(parseReadyLine('  Hermes backend listening on 127.0.0.1:62766')).toBeNull()
    expect(parseReadyLine('HERMES_BACKEND_READY port=99999')).toBeNull()
  })

  it('splits chunked output into complete lines and keeps the remainder', () => {
    const buffer = new LineBuffer()
    expect(buffer.push('HERMES_BACK')).toEqual([])
    expect(buffer.push('END_READY port=1234\nnext')).toEqual(['HERMES_BACKEND_READY port=1234'])
    expect(buffer.flush()).toEqual(['next'])
  })
})
