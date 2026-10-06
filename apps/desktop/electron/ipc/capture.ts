import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { ipcMain } from 'electron'
import { IPC } from '../../shared/ipc.ts'
import { run } from '../platform/exec.ts'

/** Screen grabs handed to Hermes; they only need to outlive the question about them. */
export function capturesDir(): string {
  return path.join(os.tmpdir(), 'herald-os-captures')
}

/**
 * Let the person draw a rectangle on screen and save it as a PNG: `screencapture -i` on macOS,
 * slurp and grim on Wayland. Resolves with the file, or null when they pressed Escape.
 */
export async function captureRegion(): Promise<string | null> {
  fs.mkdirSync(capturesDir(), { recursive: true })
  const file = path.join(capturesDir(), `region-${new Date().toISOString().replace(/[:.]/g, '-')}.png`)

  if (process.platform === 'darwin') {
    await run('screencapture', ['-i', '-x', '-t', 'png', file], 300_000)

    return fs.existsSync(file) ? file : null
  }

  if (process.platform === 'linux') {
    const region = await run('slurp', [], 300_000)

    if (region.code === 127) {
      throw new Error('slurp is not installed (it draws the selection on Wayland)')
    }

    if (region.code !== 0 || !region.stdout.trim()) {
      return null
    }

    const grab = await run('grim', ['-g', region.stdout.trim(), file], 30_000)

    if (grab.code === 127) {
      throw new Error('grim is not installed (it takes the screenshot on Wayland)')
    }

    return grab.code === 0 && fs.existsSync(file) ? file : null
  }

  throw new Error('Selecting part of the screen is not available on this platform yet')
}

export function registerCaptureIpc(): void {
  ipcMain.handle(IPC.captureRegion, () => captureRegion())
}
