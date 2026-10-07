import { describe, expect, it } from 'vitest'
import { converterHint, converters } from './convert.ts'

describe('converters', () => {
  it('uses sips on the Mac for everything', () => {
    expect(converters('/a/photo.heic', '/t/out.png', 'darwin')).toEqual([['sips', '-s', 'format', 'png', '/a/photo.heic', '--out', '/t/out.png']])
  })

  it('tries libheif first for HEIC on Linux (heif-dec, then the older heif-convert), then the general tools', () => {
    const tools = converters('/a/photo.HEIC', '/t/out.png', 'linux').map(([command]) => command)
    expect(tools).toEqual(['heif-dec', 'heif-convert', 'magick', 'convert', 'vips'])
  })

  it('tries darktable for camera RAW, and takes the first page of a PSD or TIFF', () => {
    expect(converters('/a/shot.cr3', '/t/out.png', 'linux')[0][0]).toBe('darktable-cli')
    expect(converters('/a/art.psd', '/t/out.png', 'linux')[0]).toEqual(['magick', '/a/art.psd[0]', '/t/out.png'])
    expect(converters('/a/scan.tif', '/t/out.png', 'linux').map(([command]) => command)).toEqual(['magick', 'convert', 'vips'])
  })
})

describe('converterHint', () => {
  it('names the packages to install for each kind of file', () => {
    expect(converterHint('/a/photo.heic')).toMatch(/libheif-tools on Fedora, libheif-examples on Debian/)
    expect(converterHint('/a/shot.NEF')).toMatch(/darktable/)
    expect(converterHint('/a/scan.tiff')).toMatch(/ImageMagick on Fedora.*vips-tools on Fedora/)
  })

  it('names the HEVC decoder when libheif has none (Fedora ships it without)', () => {
    const said = 'Could not decode image: Error while loading plugin: No decoding plugin installed for this compression format: HEVC (a suitable decoder plugin is libde265)'
    expect(converterHint('/a/IMG_0001.HEIC', said)).toMatch(/libheif-freeworld from RPM Fusion.*libheif-plugin-libde265/)
    expect(converterHint('/a/scan.tif', said)).toMatch(/ImageMagick/)
  })
})
