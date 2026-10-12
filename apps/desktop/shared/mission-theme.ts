/** A narrow data generator using the maintained theme SDK; no file/code authority. */
import { THEME_COLOR_KEYS, validateTheme, type ThemeSpec } from './theme.ts'

export type MissionThemeAction = { operation: 'theme.sdk' } | { operation: 'theme.stage'; theme: Omit<ThemeSpec, 'name' | 'wallpaper' | 'gtk' | 'terminal'> }
export const MISSION_THEME_SDK = { colors: [...THEME_COLOR_KEYS], shell_themes: ['ocean', 'graphite'], accents: ['blue', 'ice', 'violet'], schemes: ['dark', 'light'], wallpaper: 'drawn', executable_extensions: false }

export function missionThemeName(mission: string): string {
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(mission)) throw new Error('Canonical theme mission required')
  return 'haos-t-' + mission.replaceAll('-', '')
}

export function validateMissionThemeAction(value: unknown): MissionThemeAction {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Closed mission theme action required')
  const data = value as Record<string, unknown>
  if (data.operation === 'theme.sdk' && Object.keys(data).length === 1) return data as MissionThemeAction
  if (data.operation !== 'theme.stage' || Object.keys(data).length !== 2 || !data.theme || typeof data.theme !== 'object' || Array.isArray(data.theme)) throw new Error('Closed data theme action required')
  const theme = data.theme as Record<string, unknown>
  if (Object.keys(theme).some(key => !['colors', 'label', 'description', 'shell'].includes(key))) throw new Error('Theme paths, names, code and plugins denied')
  const problem = validateTheme({ ...theme, name: 'haos-t-fixture', wallpaper: 'default' })
  if (problem) throw new Error('Theme data does not match the installed SDK')
  return data as MissionThemeAction
}
