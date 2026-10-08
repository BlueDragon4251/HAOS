import { execFile } from 'node:child_process'
import { constants } from 'node:fs'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

/*
 * OpenDocument files through headless LibreOffice, when it is installed: `soffice --headless
 * --convert-to` turns an .odt into a .docx (and back) for Herald's own readers and writers. Each
 * run gets a profile of its own, so a LibreOffice the person has open is neither used nor disturbed.
 */

/** Formats LibreOffice is asked for: Herald's own and the OpenDocument ones. */
export const CONVERT_TARGETS: ReadonlySet<string> = new Set(['docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp', 'csv', 'pdf'])

const CONVERT_TIMEOUT_MS = 120_000

/** Where `soffice` may be, in the order to try (pure; tested). */
export function sofficeCandidates(platform: NodeJS.Platform, env: NodeJS.ProcessEnv, home = os.homedir()): string[] {
  const onPath = (env.PATH ?? '')
    .split(path.delimiter)
    .filter(Boolean)
    .flatMap((dir) => [path.join(dir, 'soffice'), path.join(dir, 'libreoffice')])

  if (platform === 'darwin') {
    return ['/Applications/LibreOffice.app/Contents/MacOS/soffice', path.join(home, 'Applications/LibreOffice.app/Contents/MacOS/soffice'), ...onPath]
  }

  return [...onPath, '/usr/bin/soffice', '/usr/lib/libreoffice/program/soffice', '/opt/libreoffice/program/soffice', '/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice']
}

let found: Promise<string | null> | null = null

/** The first `soffice` that can run here, looked for once. */
export function findSoffice(): Promise<string | null> {
  found ??= (async () => {
    for (const candidate of sofficeCandidates(process.platform, process.env)) {
      if (await fs.access(candidate, constants.X_OK).then(() => true, () => false)) {
        return candidate
      }
    }

    return null
  })()

  return found
}

/** The command line for one conversion (pure; tested). */
export function convertArgs(file: string, to: string, outDir: string, profileDir: string): string[] {
  return [`-env:UserInstallation=${pathToFileURL(profileDir).href}`, '--headless', '--norestore', '--nologo', '--nolockcheck', '--convert-to', to, '--outdir', outDir, file]
}

/** `file` converted to `to` (an extension without its dot), as the converted file's bytes. */
export async function convertWithLibreOffice(file: string, to: string): Promise<Uint8Array> {
  if (!CONVERT_TARGETS.has(to)) {
    throw new Error(`LibreOffice is not asked for .${to} files`)
  }

  const soffice = await findSoffice()

  if (!soffice) {
    throw new Error('LibreOffice is not installed')
  }

  const work = await fs.mkdtemp(path.join(os.tmpdir(), 'herald-office-convert-'))

  try {
    const outDir = path.join(work, 'out')
    await fs.mkdir(outDir)
    await new Promise<void>((resolve, reject) => {
      execFile(soffice, convertArgs(file, to, outDir, path.join(work, 'profile')), { timeout: CONVERT_TIMEOUT_MS }, (error, _stdout, stderr) => {
        if (error) {
          reject(new Error(`LibreOffice could not convert ${path.basename(file)}: ${String(stderr).trim() || error.message}`))
        } else {
          resolve()
        }
      })
    })
    const [output] = await fs.readdir(outDir)

    if (!output) {
      throw new Error(`LibreOffice did not convert ${path.basename(file)}`)
    }

    return new Uint8Array(await fs.readFile(path.join(outDir, output)))
  } finally {
    await fs.rm(work, { recursive: true, force: true })
  }
}
