/** Existing GUI broker's data-only authoring capability; no privileged bridge. */
import { MISSION_THEME_SDK, missionThemeName, validateMissionThemeAction } from '../../shared/mission-theme.ts'
import { findTheme, saveTheme, themeHistory } from '../theme/themes.ts'

export function missionTheme(request: { mission: string; action: unknown }): Record<string, unknown> {
  const name = missionThemeName(request.mission), action = validateMissionThemeAction(request.action)
  if (action.operation === 'theme.sdk') return { ...MISSION_THEME_SDK }
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
