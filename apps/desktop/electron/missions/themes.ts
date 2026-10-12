/** Existing GUI broker's data-only authoring capability; no privileged bridge. */
import { MISSION_THEME_SDK, missionThemeName, validateMissionThemeAction } from '../../shared/mission-theme.ts'
import { findTheme, saveTheme, themeHistory } from '../theme/themes.ts'
import type { ThemeIpcDeps } from '../ipc/theme.ts'

export function missionTheme(request: { mission: string; action: unknown }): Record<string, unknown> {
  const name = missionThemeName(request.mission), action = validateMissionThemeAction(request.action)
  if (action.operation === 'theme.sdk') return { ...MISSION_THEME_SDK }
  if (action.operation !== 'theme.stage') throw new Error('Asynchronous theme capability required')
  let count = 0
  try { count = themeHistory(name).length }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
  if (count >= 16) throw new Error('Mission theme revision budget exhausted')
  // The name and drawn wallpaper are broker-owned; no image path, import URL,
  // GTK command, plugin source or arbitrary observer file enters this function.
  saveTheme({ ...action.theme, name, wallpaper: 'default' })
  const saved = findTheme(name)
  if (!saved?.revision) throw new Error('Published mission theme revision is unavailable')
  return { name, revision: saved.revision, scope: 'mission-data-theme' }
}

export async function executeMissionTheme(request: { mission: string; action: unknown }, authorize: () => Promise<boolean>, deps?: ThemeIpcDeps): Promise<Record<string, unknown>> {
  const name = missionThemeName(request.mission), action = validateMissionThemeAction(request.action)
  if (!(await authorize())) throw new Error('Mission theme authority expired')
  if (action.operation === 'theme.sdk' || action.operation === 'theme.stage') return missionTheme(request)
  const found = findTheme(name, action.revision)
  if (!found?.revision || found.spec.name !== name) throw new Error('Exact mission theme revision unavailable')
  if (action.operation === 'theme.apply') {
    if (!deps?.panels || !deps.verify || process.platform !== 'linux') throw new Error('Actual guarded HAOS shell unavailable')
    const { applyTheme } = await import('../ipc/theme.ts')
    const next = await applyTheme(name, { ...deps, authorize }, action.revision)
    if (next.themeName !== name || next.themeRevision !== action.revision) throw new Error('Activated theme identity differs')
    return { name, revision: action.revision, applied: true, verified: true }
  }
  const { previewTheme } = await import('../theme/preview.ts')
  const proof = await previewTheme(found, deps?.panels ?? false)
  if (!(await authorize())) throw new Error('Mission ended during isolated preview')
  const { nativeImage } = await import('electron')
  const image = nativeImage.createFromDataURL(proof.png), size = image.getSize()
  if (image.isEmpty() || size.width !== 960 || size.height !== 640) throw new Error('Actual preview dimensions differ')
  const bytes = image.toJPEG(70)
  if (bytes.length < 100 || bytes.length > 1048576) throw new Error('Preview image budget exceeded')
  const { createHash } = await import('node:crypto')
  return { name, revision: action.revision, passed: proof.passed, checks: proof.checks,
    stylesheet_sha256: proof.stylesheetSha256, png_sha256: proof.screenshotSha256,
    mime: 'image/jpeg', bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), base64: bytes.toString('base64') }
}
