import fs from 'node:fs'
import path from 'node:path'
import type { HermesOSPrefs } from '../shared/ipc.ts'
import { hermesOsDataDir } from './paths.ts'

const DEFAULTS: HermesOSPrefs = {
  fullscreenOnLaunch: true,
  reduceMotion: false,
  accent: 'gold'
}

function prefsFile(): string {
  return path.join(hermesOsDataDir(), 'prefs.json')
}

export function readPrefs(): HermesOSPrefs {
  try {
    const parsed = JSON.parse(fs.readFileSync(prefsFile(), 'utf8')) as Partial<HermesOSPrefs>

    return { ...DEFAULTS, ...parsed }
  } catch {
    return { ...DEFAULTS }
  }
}

export function writePrefs(patch: Partial<HermesOSPrefs>): HermesOSPrefs {
  const next = { ...readPrefs(), ...patch }
  fs.mkdirSync(hermesOsDataDir(), { recursive: true })
  fs.writeFileSync(prefsFile(), JSON.stringify(next, null, 2))

  return next
}
