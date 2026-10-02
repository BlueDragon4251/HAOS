import { atom } from 'nanostores'
import type { BackendState, EnvInfo, HeraldOSPrefs, WindowState } from '../../shared/ipc.ts'
import { VOICE_DEFAULTS } from '../../shared/voice-prefs.ts'

/** Cache of Electron's backend truth; Electron is authoritative. */
export const $backend = atom<BackendState>({ phase: 'idle', attempt: 0, logTail: [] })
export const $windowState = atom<WindowState>({ fullscreen: false, focused: true })
export const $env = atom<EnvInfo | null>(null)
export const $prefs = atom<HeraldOSPrefs>({
  fullscreenOnLaunch: true,
  reduceMotion: false,
  accent: 'blue',
  theme: 'ocean',
  spaces: [{ id: 'personal', name: 'Personal', color: '#4d92ff' }],
  activeSpace: 'personal',
  favorites: [],
  voice: VOICE_DEFAULTS
})

export function applyPrefsToDocument(prefs: HeraldOSPrefs): void {
  document.documentElement.dataset.accent = prefs.accent
  document.documentElement.dataset.theme = prefs.theme
  document.documentElement.dataset.reduceMotion = String(prefs.reduceMotion)
}

export async function updatePrefs(patch: Partial<HeraldOSPrefs>): Promise<void> {
  const next = await window.heraldOS.prefs.set(patch)
  $prefs.set(next)
  applyPrefsToDocument(next)
}

export function bindBackendStores(): () => void {
  const offBackend = window.heraldOS.backend.onState(state => $backend.set(state))
  const offWindow = window.heraldOS.window.onState(state => $windowState.set(state))
  void window.heraldOS.backend.getState().then(state => $backend.set(state))
  void window.heraldOS.window.getState().then(state => $windowState.set(state))
  void window.heraldOS.env().then(info => $env.set(info))
  void window.heraldOS.prefs.get().then(prefs => {
    $prefs.set(prefs)
    applyPrefsToDocument(prefs)
  })
  // Preferences changed by another surface window or by the `herald-os` CLI (theme, wallpaper).
  const offPrefs = window.heraldOS.prefs.onChanged?.(prefs => {
    $prefs.set(prefs)
    applyPrefsToDocument(prefs)
  })

  return () => {
    offBackend()
    offWindow()
    offPrefs?.()
  }
}
