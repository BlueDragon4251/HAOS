import { describe, expect, it } from 'vitest'
import { converters } from './convert.ts'

describe('converters', () => {
  it('uses sips on the Mac for everything', () => {
    expect(converters('/a/photo.heic', '/t/out.png', 'darwin')).toEqual([['sips', '-s', 'format', 'png', '/a/photo.heic', '--out', '/t/out.png']])
  })

  it('tries libheif first for HEIC on Linux, then the general tools', () => {
    const tools = converters('/a/photo.HEIC', '/t/out.png', 'linux').map(([command]) => command)
    expect(tools).toEqual(['heif-convert', 'magick', 'convert', 'vips'])
  })

  it('tries darktable for camera RAW, and takes the first page of a PSD or TIFF', () => {
    expect(converters('/a/shot.cr3', '/t/out.png', 'linux')[0][0]).toBe('darktable-cli')
    expect(converters('/a/art.psd', '/t/out.png', 'linux')[0]).toEqual(['magick', '/a/art.psd[0]', '/t/out.png'])
  })
})
