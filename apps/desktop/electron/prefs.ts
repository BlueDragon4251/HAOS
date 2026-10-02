import fs from 'node:fs'
import path from 'node:path'
import type { HeraldOSPrefs } from '../shared/ipc.ts'
import { normalizeVoicePrefs, VOICE_DEFAULTS } from '../shared/voice-prefs.ts'
import { heraldOsDataDir } from './paths.ts'

const DEFAULTS: HeraldOSPrefs = {
  voice: VOICE_DEFAULTS,
  fullscreenOnLaunch: true,
  reduceMotion: false,
  accent: 'blue',
  theme: 'ocean',
  spaces: [
    { id: 'personal', name: 'Personal', color: '#4d92ff' },
    { id: 'work', name: 'Work', color: '#36e6a6' },
    { id: 'ideas', name: 'Ideas', color: '#b47cff' }
  ],
  activeSpace: 'personal',
  favorites: []
}

function prefsFile(): string {
  return path.join(heraldOsDataDir(), 'prefs.json')
}

export function readPrefs(): HeraldOSPrefs {
  try {
    const parsed = JSON.parse(fs.readFileSync(prefsFile(), 'utf8')) as Omit<Partial<HeraldOSPrefs>, 'accent'> & { accent?: string }
    // Accent names from the first alpha.
    const legacy: Record<string, HeraldOSPrefs['accent']> = { gold: 'blue', jade: 'violet', blue: 'blue', ice: 'ice', violet: 'violet' }
    const accent = parsed.accent ? legacy[parsed.accent] : undefined

    return {
      ...DEFAULTS,
      ...parsed,
      accent: (accent as HeraldOSPrefs['accent']) ?? DEFAULTS.accent,
      spaces: parsed.spaces?.length ? parsed.spaces : DEFAULTS.spaces,
      voice: normalizeVoicePrefs(parsed.voice)
    }
  } catch {
    return { ...DEFAULTS }
  }
}

export function writePrefs(patch: Partial<HeraldOSPrefs>): HeraldOSPrefs {
  const current = readPrefs()
  // `voice` is the one nested pref object callers patch field by field; merge instead of replacing.
  const next = { ...current, ...patch, voice: normalizeVoicePrefs({ ...current.voice, ...(patch.voice ?? {}) }) }
  fs.mkdirSync(heraldOsDataDir(), { recursive: true })
  fs.writeFileSync(prefsFile(), JSON.stringify(next, null, 2))

  return next
}
