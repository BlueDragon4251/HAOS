import { execFile } from 'node:child_process'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'

/*
 * Images Chromium cannot decode (HEIC, TIFF, camera RAW, PSD) become a PNG through whatever the
 * system has: `sips` on the Mac (ImageIO reads all of them), and on Linux libheif, darktable,
 * ImageMagick or libvips, tried in turn.
 */

const run = promisify(execFile)

const RAW = new Set(['.dng', '.cr2', '.cr3', '.nef', '.arw', '.raf', '.orf', '.rw2'])

/** Converter commands to try, in order, for a file (pure; tested). */
export function converters(file: string, out: string, platform: NodeJS.Platform = process.platform): string[][] {
  if (platform === 'darwin') {
    return [['sips', '-s', 'format', 'png', file, '--out', out]]
  }

  const extension = path.extname(file).toLowerCase()
  const commands: string[][] = []

  if (extension === '.heic' || extension === '.heif') {
    commands.push(['heif-convert', file, out])
  }

  if (RAW.has(extension)) {
    commands.push(['darktable-cli', file, out])
  }

  // `[0]` takes the first frame or page: the flattened image of a PSD or a multi-page TIFF.
  commands.push(['magick', `${file}[0]`, out], ['convert', `${file}[0]`, out], ['vips', 'copy', file, out])

  return commands
}

export async function convertToPng(file: string): Promise<Uint8Array> {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), 'herald-canvas-'))
  const out = path.join(folder, 'image.png')

  try {
    for (const [command, ...args] of converters(file, out)) {
      try {
        await run(command, args, { timeout: 180_000 })
        const bytes = await fs.readFile(out)

        if (bytes.length) {
          return new Uint8Array(bytes)
        }
      } catch {
        // Not installed, or it could not read this file: try the next one.
      }
    }

    throw new Error(`Nothing on this computer can open ${path.extname(file)} files${process.platform === 'linux' ? ' yet: install ImageMagick (or libheif for HEIC, darktable for RAW)' : ''}`)
  } finally {
    await fs.rm(folder, { recursive: true, force: true })
  }
}
