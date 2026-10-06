import { describe, expect, it } from 'vitest'
import { brandingFileName, brandingName } from './branding.ts'

describe('brandingName', () => {
  it('keeps one short line', () => {
    expect(brandingName('  Acme   Corp ')).toBe('Acme Corp')
    expect(brandingName('Line one\nLine two\u0007')).toBe('Line one Line two')
    expect(brandingName('x'.repeat(60))).toHaveLength(40)
    expect(brandingName('   ')).toBeNull()
    expect(brandingName(42)).toBeNull()
  })
})

describe('brandingFileName', () => {
  it('names the copy after its kind and keeps the format', () => {
    expect(brandingFileName('logo', '/home/me/Acme Logo.SVG')).toEqual({ file: 'logo.svg' })
    expect(brandingFileName('lock', '/home/me/beach.jpeg')).toEqual({ file: 'lock.jpg' })
    expect(brandingFileName('logo', '/home/me/mark.webp')).toEqual({ file: 'logo.webp' })
  })

  it('refuses what the lock screen or About cannot show', () => {
    expect(brandingFileName('lock', '/home/me/mark.svg')).toEqual({ error: 'The lock-screen picture must be .png, .jpg' })
    expect('error' in brandingFileName('logo', '/home/me/notes.txt')).toBe(true)
    expect('error' in brandingFileName('logo', '/home/me/no-extension')).toBe(true)
  })
})
