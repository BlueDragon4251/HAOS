import { describe, expect, it } from 'vitest'
import { DEFAULT_HAOS_REGION, validHaosRegion } from './region.ts'

describe('HAOS keyboard and language selection', () => {
  it('provides a predictable offline default', () => {
    expect(validHaosRegion(DEFAULT_HAOS_REGION)).toBe(true)
  })
  it('accepts independently selected Austrian German and Swiss keyboard', () => {
    expect(validHaosRegion({ language: 'de_AT.UTF-8', keyboard: 'at' })).toBe(true)
    expect(validHaosRegion({ language: 'de_DE.UTF-8', keyboard: 'ch' })).toBe(true)
  })
  it('rejects command and filesystem injection', () => {
    for (const setting of [
      { language: 'de_AT.UTF-8\nPATH=/tmp', keyboard: 'at' },
      { language: 'de_AT.UTF-8', keyboard: 'at"; spawn "sh"' },
      { language: 'de_AT.UTF-8', keyboard: '../' },
      { language: 'de_AT.UTF-8', keyboard: 'at', extra: true },
      null
    ]) {
      expect(validHaosRegion(setting)).toBe(false)
    }
  })
})
