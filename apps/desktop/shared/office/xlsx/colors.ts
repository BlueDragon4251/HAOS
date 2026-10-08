import { elementsOf, firstElement } from './xml.ts'

/*
 * Excel's colours as the RGB Univer draws: theme colours with their tint worked out, the legacy
 * indexed palette (or the file's own), and plain ARGB. Univer keeps only RGB, so a theme colour is
 * saved as the colour it showed.
 */

export interface ExcelColor {
  argb?: string
  theme?: number
  tint?: number
  indexed?: number
}

/** The colours a file's colours refer to: its theme, in Excel's theme index order, and its palette. */
export interface Palette {
  theme: string[]
  indexed: string[]
}

/** Office's theme (2013 to 2022), for a file without one: lt1, dk1, lt2, dk2, accent 1 to 6, hyperlink, followed hyperlink. */
export const OFFICE_THEME = ['FFFFFF', '000000', 'E7E6E6', '44546A', '4472C4', 'ED7D31', 'A5A5A5', 'FFC000', '5B9BD5', '70AD47', '0563C1', '954F72']

const LEGACY_PALETTE = (
  '000000 FFFFFF FF0000 00FF00 0000FF FFFF00 FF00FF 00FFFF 000000 FFFFFF FF0000 00FF00 0000FF FFFF00 FF00FF 00FFFF ' +
  '800000 008000 000080 808000 800080 008080 C0C0C0 808080 9999FF 993366 FFFFCC CCFFFF 660066 FF8080 0066CC CCCCFF ' +
  '000080 FF00FF FFFF00 00FFFF 800080 800000 008080 0000FF 00CCFF CCFFFF CCFFCC FFFF99 99CCFF FF99CC CC99FF FFCC99 ' +
  '3366FF 33CCCC 99CC00 FFCC00 FF9900 FF6600 666699 969696 003366 339966 003300 333300 993300 993366 333399 333333'
).split(' ')

export const DEFAULT_PALETTE: Palette = { theme: OFFICE_THEME, indexed: LEGACY_PALETTE }

/** The scheme's colours in theme index order (the scheme lists dk1 before lt1; indexes swap them). */
export function themeColors(themeXml: string | undefined): string[] {
  const scheme = themeXml ? firstElement(themeXml, 'clrScheme') : undefined

  if (!scheme) {
    return OFFICE_THEME
  }

  const colorOf = (name: string, fallback: string): string => {
    const slot = firstElement(scheme.inner, name)
    const rgb = slot && (firstElement(slot.inner, 'srgbClr')?.attributes.val ?? firstElement(slot.inner, 'sysClr')?.attributes.lastClr)

    return rgb && /^[0-9a-f]{6}$/i.test(rgb) ? rgb.toUpperCase() : fallback
  }

  return ['lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink'].map((name, i) => colorOf(name, OFFICE_THEME[i]))
}

/** A file's own indexed palette (styles.xml `<indexedColors>`), or the legacy one. */
export function indexedColors(stylesXml: string | undefined): string[] {
  const custom = stylesXml ? firstElement(stylesXml, 'indexedColors') : undefined
  const colors = custom ? elementsOf(custom.inner, 'rgbColor').map((entry) => (entry.attributes.rgb ?? '').slice(-6).toUpperCase()) : []

  return colors.length ? LEGACY_PALETTE.map((fallback, i) => (/^[0-9A-F]{6}$/.test(colors[i] ?? '') ? colors[i] : fallback)) : LEGACY_PALETTE
}

function toHls(hex: string): [number, number, number] {
  const [r, g, b] = [0, 2, 4].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255)
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2

  if (max === min) {
    return [0, l, 0]
  }

  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4

  return [h / 6, l, s]
}

function fromHls(h: number, l: number, s: number): string {
  const channel = (t: number, p: number, q: number): number => {
    const x = t < 0 ? t + 1 : t > 1 ? t - 1 : t

    return x < 1 / 6 ? p + (q - p) * 6 * x : x < 1 / 2 ? q : x < 2 / 3 ? p + (q - p) * (2 / 3 - x) * 6 : p
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  const rgb = s === 0 ? [l, l, l] : [channel(h + 1 / 3, p, q), channel(h, p, q), channel(h - 1 / 3, p, q)]

  return rgb.map((v) => Math.round(v * 255).toString(16).padStart(2, '0')).join('').toUpperCase()
}

/** A tint as Excel applies it: towards black below zero, towards white above (on HLS lightness). */
export function tinted(hex: string, tint: number | undefined): string {
  if (!tint) {
    return hex.toUpperCase()
  }

  const [h, l, s] = toHls(hex)
  const lightness = tint < 0 ? l * (1 + tint) : l * (1 - tint) + tint

  return fromHls(h, Math.min(1, Math.max(0, lightness)), s)
}

/** An ExcelJS colour as "#rrggbb"; null for none or "automatic" (indexed 64 and 65 follow the window). */
export function resolveColor(color: ExcelColor | undefined, palette: Palette): string | null {
  if (!color) {
    return null
  }

  let hex: string | undefined

  if (typeof color.argb === 'string' && /^[0-9a-f]{6,8}$/i.test(color.argb)) {
    hex = color.argb.slice(-6)
  } else if (typeof color.theme === 'number') {
    hex = palette.theme[color.theme] ?? OFFICE_THEME[color.theme]
  } else if (typeof color.indexed === 'number') {
    hex = palette.indexed[color.indexed]
  }

  return hex ? `#${tinted(hex, color.tint).toLowerCase()}` : null
}

/** A colour as Univer may hold it ("#rgb", "#rrggbb", "rgb(…)", "rgba(…)") as ExcelJS's ARGB; null when it is not one. */
export function argbOf(color: string | null | undefined): string | null {
  const text = String(color ?? '').trim().toLowerCase()
  const short = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/.exec(text)

  if (short) {
    return `FF${short[1]}${short[1]}${short[2]}${short[2]}${short[3]}${short[3]}`.toUpperCase()
  }

  const long = /^#([0-9a-f]{6})(?:[0-9a-f]{2})?$/.exec(text)

  if (long) {
    return `FF${long[1]}`.toUpperCase()
  }

  const functional = /^rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})/.exec(text)

  if (functional) {
    return `FF${functional.slice(1, 4).map((v) => Math.min(255, Number(v)).toString(16).padStart(2, '0')).join('')}`.toUpperCase()
  }

  return null
}

/** "#rrggbb" for any colour argbOf reads; null otherwise. */
export const hexOf = (color: string | null | undefined): string | null => {
  const argb = argbOf(color)

  return argb ? `#${argb.slice(2).toLowerCase()}` : null
}

/** Two colours mixed, `amount` of the first: how a patterned fill looks from a distance. */
export function mixed(first: string, second: string, amount: number): string {
  const channels = (hex: string) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16))
  const [a, b] = [channels(first), channels(second)]

  return `#${a.map((v, i) => Math.round(v * amount + b[i] * (1 - amount)).toString(16).padStart(2, '0')).join('')}`
}
