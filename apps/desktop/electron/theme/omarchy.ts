import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { isHexColor, mix, schemeOf, type ThemeColors, type ThemeSpec, themeSlug } from '../../shared/theme.ts'

/*
 * Herald inside Omarchy follows Omarchy's theme: the active one is ~/.config/omarchy/current/theme
 * (a link to the theme's folder), whose colors.toml (or, in older themes, alacritty.toml) holds the
 * palette. Omarchy runs `herald-os theme omarchy` from its theme-set hook when the theme changes.
 */

export function omarchyDir(home = os.homedir()): string {
  return path.join(home, '.config', 'omarchy')
}

export function isOmarchy(home = os.homedir()): boolean {
  return fs.existsSync(path.join(home, '.local', 'share', 'omarchy')) || fs.existsSync(path.join(omarchyDir(home), 'current', 'theme'))
}

/** `key = "value"` pairs from a TOML file, keyed both plainly and by section (`colors.primary.background`). */
export function parseTomlStrings(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  let section = ''

  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/\s+#.*$/, '').trim()
    const header = /^\[([^\]]+)\]$/.exec(line)

    if (header) {
      section = (header[1] ?? '').trim()

      continue
    }

    const pair = /^([A-Za-z0-9_.-]+)\s*=\s*["']([^"']*)["']/.exec(line)

    if (pair) {
      const key = pair[1] as string
      const value = (pair[2] as string).trim().replace(/^0x/i, '#')
      out[section ? `${section}.${key}` : key] = value
      out[key] ??= value
    }
  }

  return out
}

/** Herald's colours from Omarchy's (or alacritty's) palette; null without a background and foreground. */
export function themeColorsFromOmarchy(values: Record<string, string>): ThemeColors | null {
  const get = (...keys: string[]) => keys.map(key => values[key]).find(isHexColor)
  const bg = get('background', 'colors.primary.background', 'base00', 'color0')
  const fg = get('foreground', 'colors.primary.foreground', 'base05', 'color7')

  if (!bg || !fg) {
    return null
  }

  const accent = get('accent', 'colors.normal.blue', 'color4', 'base0D', 'cursor', 'colors.cursor.cursor') ?? mix(fg, bg, 0.3)

  return {
    bg,
    bg2: mix(bg, accent, 0.1),
    surface: get('selection_background', 'colors.selection.background', 'base02') ?? mix(bg, fg, 0.12),
    fg,
    fg_dim: get('colors.dim.foreground', 'base04') ?? mix(fg, bg, 0.4),
    accent,
    accent_strong: get('colors.bright.blue', 'color12', 'base0C') ?? accent,
    border_active: accent,
    border_inactive: mix(bg, fg, 0.15),
    urgent: get('colors.normal.red', 'color1', 'base08', 'red') ?? '#ff6b6b',
    ok: get('colors.normal.green', 'color2', 'base0B', 'green') ?? '#36e6a6',
    warn: get('colors.normal.yellow', 'color3', 'base0A', 'yellow') ?? '#f2c25e'
  }
}

/** The active Omarchy theme as a Herald theme, with Omarchy's background as the wallpaper. */
export function readOmarchyTheme(home = os.homedir()): { spec: ThemeSpec; dir: string } | null {
  const link = path.join(omarchyDir(home), 'current', 'theme')
  let dir: string

  try {
    dir = fs.realpathSync(link)
  } catch {
    return null
  }

  for (const file of ['colors.toml', 'alacritty.toml']) {
    let text: string

    try {
      text = fs.readFileSync(path.join(dir, file), 'utf8')
    } catch {
      continue
    }

    const colors = themeColorsFromOmarchy(parseTomlStrings(text))

    if (!colors) {
      continue
    }

    const name = path.basename(dir)
    let wallpaper: string | undefined

    try {
      wallpaper = fs.realpathSync(path.join(omarchyDir(home), 'current', 'background'))
    } catch {
      wallpaper = undefined
    }

    return {
      dir,
      spec: {
        name: `omarchy-${themeSlug(name)}`,
        label: `Omarchy: ${name.replace(/[-_]+/g, ' ')}`,
        description: "Follows Omarchy's theme",
        shell: { scheme: schemeOf(colors) },
        colors,
        ...(wallpaper ? { wallpaper } : {})
      }
    }
  }

  return null
}
