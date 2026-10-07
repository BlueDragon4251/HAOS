import { describe, expect, it } from 'vitest'
import { baseName, canOpenInCanvas, CONVERTED_IMAGE_EXTENSIONS, isLayeredImage, isProjectPath, projectContaining } from './files.ts'

describe('what Herald Canvas opens', () => {
  it('opens projects, images, converted formats and Photoshop documents', () => {
    expect(isProjectPath('/a/Poster.comp/')).toBe(true)
    expect(canOpenInCanvas('/a/photo.JPG')).toBe(true)
    expect(canOpenInCanvas('/a/photo.heic')).toBe(true)
    expect(canOpenInCanvas('/a/notes.txt')).toBe(false)
  })

  it('reads Photoshop documents itself, with their layers, rather than through the system', () => {
    expect(isLayeredImage('/a/Art.PSD')).toBe(true)
    expect(isLayeredImage('/a/Huge.psb')).toBe(true)
    expect(isLayeredImage('/a/photo.tif')).toBe(false)
    expect(CONVERTED_IMAGE_EXTENSIONS.has('.psd')).toBe(false)
    expect(canOpenInCanvas('/a/Art.psd')).toBe(true)
  })

  it('finds the project a file lies in, and names files', () => {
    expect(projectContaining('/a/Poster.comp/images/X.png')).toBe('/a/Poster.comp')
    expect(projectContaining('/a/photo.png')).toBeNull()
    expect(baseName('/a/Night market.psd')).toBe('Night market')
  })
})
