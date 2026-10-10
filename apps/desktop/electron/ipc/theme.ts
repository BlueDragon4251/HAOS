import fs from 'node:fs'
import { ipcMain, nativeImage } from 'electron'
import { type HeraldOSPrefs, IPC } from '../../shared/ipc.ts'
import { HERALD_SKIN, type ThemeSpec } from '../../shared/theme.ts'
import type { BackendManager } from '../backend/manager.ts'
import { events } from '../events/bus.ts'
import { log } from '../log.ts'
import { run } from '../platform/exec.ts'
import { readPrefs, writePrefs } from '../prefs.ts'
import { findTheme, installTheme, listFonts, listThemes, prefsForTheme, saveTheme, themeHistory, writeHermesSkin } from '../theme/themes.ts'
import { previewTheme } from '../theme/preview.ts'

export interface ThemeIpcDeps {
  panels: boolean
  /** Push new preferences to every window (and the wallpaper service). */
  broadcast: (prefs: HeraldOSPrefs) => void
  backend: BackendManager
  /** Verify the actual connected shell after applying preferences, before confirmation. */
  verify?: (prefs: HeraldOSPrefs) => Promise<boolean>
}

/**
 * Point Hermes at the Herald skin, unless the person picked another skin themselves (Hermes's
 * `display.skin`); then their choice stands, and the skin file still follows the theme.
 */
export async function selectHermesSkin(backend: BackendManager): Promise<void> {
  if (backend.getState().phase !== 'ready') {
    return
  }

  const saved = await backend.rest<{ display?: { skin?: unknown } }>({ method: 'GET', path: '/api/config', query: { include_defaults: false } })
  const skin = typeof saved?.display?.skin === 'string' ? saved.display.skin : ''

  if (skin === '' || skin === 'default') {
    await backend.rest({ method: 'PUT', path: '/api/config', body: { config: { display: { skin: HERALD_SKIN } } } })
  }
}

/** Dress Hermes in a theme that was just applied (best effort: the theme stands either way). */
export function syncHermesSkin(spec: ThemeSpec, backend: BackendManager): void {
  writeHermesSkin(spec)
  selectHermesSkin(backend).catch(error => log('theme', `could not select the Herald skin: ${(error as Error).message}`))
}

/** Apply an installed theme everywhere it reaches. */
export async function applyTheme(name: string, deps: ThemeIpcDeps, revision?: string): Promise<HeraldOSPrefs> {
  const found = findTheme(name, revision)

  if (!found) {
    throw new Error(`No theme called "${name}"`)
  }

  // Validate new saved bundles in a real isolated renderer before touching the
  // current session or preferences. An unreadable/undecodable update is a draft.
  if (found.revision && !(await previewTheme(found, deps.panels)).passed) {
    throw new Error('Theme preview failed its readability, raster or isolation checks; the previous theme remains in use')
  }

  let guard: string | undefined
  // Saved Linux session themes use an independent, unprivileged rollback process.
  // The fixed file outputs and theme-only preferences remain pending until the
  // actual connected shell renders the new preference state successfully.
  if (deps.panels && process.platform === 'linux') {
    if (found.revision && !deps.verify) throw new Error('Actual shell verification is unavailable')
    const result = await run('herald-os-theme', found.revision
      ? ['guarded-set', found.spec.name, '--revision', found.revision, '--parent', String(process.pid)]
      : ['set', found.spec.name], 10_000)

    if (result.code !== 0 && (found.revision || result.code !== 127)) {
      throw new Error('The theme engine could not start a verified activation; inspect its private recovery state')
    }
    if (found.revision) {
      const receipt = JSON.parse(result.stdout.trim().split('\n').at(-1) || '{}') as Record<string, unknown>
      if (receipt.pending !== true || typeof receipt.theme_guard !== 'string' || !/^[a-f0-9-]{36}$/.test(receipt.theme_guard)) throw new Error('Invalid theme activation receipt')
      guard = receipt.theme_guard
    }
  }

  try {
    const next = writePrefs({ ...prefsForTheme(found.spec, found.dir), themeRevision: found.revision })
    deps.broadcast(next)
    if (guard) {
      if (!(await deps.verify!(next))) throw new Error('The actual shell did not verify the tested theme')
      const result = await run('herald-os-theme', ['confirm', guard], 8_000)
      if (result.code !== 0) throw new Error('Theme activation could not be confirmed')
    }
    syncHermesSkin(found.spec, deps.backend)
    events.emit('theme-set', { theme: found.spec.name })

    return next
  } catch (error) {
    if (guard) {
      const recovery = await run('herald-os-theme', ['recover'], 8_000)
      if (recovery.code !== 0) throw new Error('Theme recovery preserved a conflict; inspect the private activation journal')
      deps.broadcast(readPrefs())
    }
    throw error
  }
}

const SAMPLE_MAX_BYTES = 80 * 1024 * 1024

/** Shrink an image to a few thousand pixels: enough to find its colours, small enough to send. */
function sampleImage(target: string): string | null {
  const file = target.replace(/^file:\/\//, '')
  const stat = fs.statSync(file, { throwIfNoEntry: false })

  if (!stat?.isFile() || stat.size > SAMPLE_MAX_BYTES) {
    return null
  }

  const image = nativeImage.createFromPath(file)

  if (image.isEmpty()) {
    return null
  }

  const { width, height } = image.getSize()
  const small = width >= height ? image.resize({ width: Math.min(width, 96), quality: 'good' }) : image.resize({ height: Math.min(height, 96), quality: 'good' })

  return small.toDataURL()
}

export function registerThemeIpc(deps: ThemeIpcDeps): void {
  ipcMain.handle(IPC.themeList, () => listThemes())
  ipcMain.handle(IPC.themeHistory, (_event, name: string) => themeHistory(name))
  ipcMain.handle(IPC.themePreview, (_event, name: string, revision?: string) => {
    const found = findTheme(name, revision)
    if (!found) throw new Error('Theme is unavailable')
    return previewTheme(found, deps.panels)
  })
  ipcMain.handle(IPC.themeSample, (_event, target: string) => sampleImage(String(target)))
  ipcMain.handle(IPC.themeApply, (_event, name: string, revision?: string) => applyTheme(String(name), deps, revision))
  ipcMain.handle(IPC.themeSave, (_event, spec: ThemeSpec, imagePath?: string) => saveTheme(spec, imagePath ? String(imagePath) : undefined))
  ipcMain.handle(IPC.themeInstall, (_event, url: string) => installTheme(String(url)))
  ipcMain.handle(IPC.fontsList, () => listFonts())
}
