import { atom } from 'nanostores'
import type { BackendState, EnvInfo, HermesOSPrefs, WindowState } from '../../shared/ipc.ts'
import { VOICE_DEFAULTS } from '../../shared/voice-prefs.ts'

/** Cache of Electron's backend truth; Electron is authoritative. */
export const $backend = atom<BackendState>({ phase: 'idle', attempt: 0, logTail: [] })
export const $windowState = atom<WindowState>({ fullscreen: false, focused: true })
export const $env = atom<EnvInfo | null>(null)
export const $prefs = atom<HermesOSPrefs>({
  fullscreenOnLaunch: true,
  reduceMotion: false,
  accent: 'blue',
  theme: 'ocean',
  spaces: [{ id: 'personal', name: 'Personal', color: '#4d92ff' }],
  activeSpace: 'personal',
  favorites: [],
  voice: VOICE_DEFAULTS
})

export function applyPrefsToDocument(prefs: HermesOSPrefs): void {
  document.documentElement.dataset.accent = prefs.accent
  document.documentElement.dataset.theme = prefs.theme
  document.documentElement.dataset.reduceMotion = String(prefs.reduceMotion)
}

export async function updatePrefs(patch: Partial<HermesOSPrefs>): Promise<void> {
  const next = await window.hermesOS.prefs.set(patch)
  $prefs.set(next)
  applyPrefsToDocument(next)
}

export function bindBackendStores(): () => void {
  const offBackend = window.hermesOS.backend.onState(state => $backend.set(state))
  const offWindow = window.hermesOS.window.onState(state => $windowState.set(state))
  void window.hermesOS.backend.getState().then(state => $backend.set(state))
  void window.hermesOS.window.getState().then(state => $windowState.set(state))
  void window.hermesOS.env().then(info => $env.set(info))
  void window.hermesOS.prefs.get().then(prefs => {
    $prefs.set(prefs)
    applyPrefsToDocument(prefs)
  })
  // Preferences changed by another surface window or by the `hermes-os` CLI (theme, wallpaper).
  const offPrefs = window.hermesOS.prefs.onChanged?.(prefs => {
    $prefs.set(prefs)
    applyPrefsToDocument(prefs)
  })

  return () => {
    offBackend()
    offWindow()
    offPrefs?.()
  }
}
