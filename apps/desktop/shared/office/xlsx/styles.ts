import type { Alignment, Borders, Fill, Font, Style } from 'exceljs'
import { argbOf, type ExcelColor, hexOf, mixed, type Palette, resolveColor } from './colors.ts'

/*
 * Cell formats between ExcelJS and Univer: fonts, fills, borders, alignment and number formats.
 * Univer keeps a sheet-wide default style (the file's Normal font) under each cell's own, so a
 * cell's style holds only what differs from that default. What Univer cannot show is drawn as the
 * nearest thing it can, with a note.
 */

/** Univer's style fields (`IStyleData`), as plain data. */
export interface UStyle {
  ff?: string
  fs?: number
  bl?: 0 | 1
  it?: 0 | 1
  ul?: { s: 0 | 1; t?: number }
  st?: { s: 0 | 1 }
  cl?: { rgb?: string | null }
  va?: number
  bg?: { rgb?: string | null }
  bd?: Partial<Record<BorderSide, { s: number; cl?: { rgb?: string | null } } | null>>
  n?: { pattern: string } | null
  ht?: number
  vt?: number
  tb?: number
  tr?: { a: number; v?: 0 | 1 }
  stf?: 0 | 1
  pd?: { t?: number; r?: number; b?: number; l?: number }
}

type BorderSide = 't' | 'r' | 'b' | 'l' | 'tl_br' | 'bl_tr' | 'tl_bc' | 'tl_mr' | 'ml_tr' | 'bc_tr'

/** Univer's enum values (core's `HorizontalAlign`, `VerticalAlign`, `WrapStrategy`, `TextDecoration`, `BaselineOffset`). */
export const ALIGN = { left: 1, center: 2, right: 3, justify: 4, distributed: 6 } as const
export const VALIGN = { top: 1, middle: 2, bottom: 3 } as const
export const WRAP = { overflow: 1, clip: 2, wrap: 3 } as const
const DECORATION = { double: 10, single: 12, singleAccounting: 18, doubleAccounting: 19 } as const
const BASELINE = { subscript: 2, superscript: 3 } as const

/** Excel's border styles in Univer's `BorderStyleTypes` order. */
const BORDERS = ['none', 'thin', 'hair', 'dotted', 'dashed', 'dashDot', 'dashDotDot', 'double', 'medium', 'mediumDashed', 'mediumDashDot', 'mediumDashDotDot', 'slantDashDot', 'thick'] as const

/** Univer's padding without one of its own: an indent level adds about three spaces to it. */
const PADDING = { t: 0, b: 2, l: 2, r: 2 }
const INDENT_PIXELS = 9

/** The workbook's Normal font, which cells fall back on. */
export interface BaseFont {
  name: string
  size: number
  /** "#rrggbb" when the Normal font has a colour of its own (not automatic). */
  color: string | null
}

export const EXCEL_BASE: BaseFont = { name: 'Calibri', size: 11, color: null }

/** The default style a sheet gets for its Normal font. */
export const baseStyle = (base: BaseFont): UStyle => ({ ff: base.name, fs: base.size, ...(base.color ? { cl: { rgb: base.color } } : {}) })

/** How dense each pattern is: the share of the pattern colour seen from a distance. */
const PATTERN_DENSITY: Record<string, number> = {
  gray0625: 0.0625,
  gray125: 0.125,
  lightGray: 0.25,
  mediumGray: 0.5,
  darkGray: 0.75,
  lightHorizontal: 0.25,
  lightVertical: 0.25,
  lightDown: 0.25,
  lightUp: 0.25,
  lightGrid: 0.4,
  lightTrellis: 0.4,
  darkHorizontal: 0.5,
  darkVertical: 0.5,
  darkDown: 0.5,
  darkUp: 0.5,
  darkGrid: 0.75,
  darkTrellis: 0.75
}

/** Built-in date formats ExcelJS names as written for any locale; Excel in English shows them as these. */
const SHOWN_AS: Record<string, string> = { 'mm-dd-yy': 'm/d/yyyy', 'm/d/yy h:mm': 'm/d/yyyy h:mm' }

export interface StyleNotes {
  add: (note: string) => void
}

export const NOTES = {
  pattern: 'Patterned cell fills are shown as solid colours.',
  gradient: 'Gradient cell fills are shown as solid colours.',
  alignment: 'Some alignments (fill, centre across selection, justify down) are shown as the nearest one Herald Sheets has.'
} as const

/** A font's own settings, those that differ from `base`, as Univer text style fields (cells and rich text runs both use these). */
export function fontStyle(font: Partial<Font> | undefined, base: BaseFont, palette: Palette): UStyle {
  const style: UStyle = {}

  if (!font) {
    return style
  }

  if (font.name && font.name !== base.name) {
    style.ff = font.name
  }

  if (typeof font.size === 'number' && font.size > 0 && font.size !== base.size) {
    style.fs = font.size
  }

  if (font.bold) {
    style.bl = 1
  }

  if (font.italic) {
    style.it = 1
  }

  if (font.underline && font.underline !== 'none') {
    const kind = font.underline === true ? 'single' : font.underline
    style.ul = kind === 'single' ? { s: 1 } : { s: 1, t: DECORATION[kind] }
  }

  if (font.strike) {
    style.st = { s: 1 }
  }

  if (font.vertAlign) {
    style.va = BASELINE[font.vertAlign]
  }

  const color = resolveColor(font.color as ExcelColor | undefined, palette)

  if (color && color !== base.color && !(base.color === null && isAutomatic(font.color as ExcelColor))) {
    style.cl = { rgb: color }
  }

  return style
}

/** Text colour that means "automatic": the theme's dark 1 without a tint, or the window colour. */
const isAutomatic = (color: ExcelColor | undefined): boolean => Boolean(color) && ((color!.theme === 1 && !color!.tint) || color!.indexed === 64)

function fillStyle(fill: Fill | undefined, palette: Palette, notes: StyleNotes): UStyle['bg'] | undefined {
  if (!fill) {
    return undefined
  }

  if (fill.type === 'gradient') {
    const stops = fill.stops.map((stop) => resolveColor(stop.color as ExcelColor, palette)).filter((color): color is string => Boolean(color))

    if (!stops.length) {
      return undefined
    }

    notes.add(NOTES.gradient)

    return { rgb: stops.length > 1 ? mixed(stops[0], stops[stops.length - 1], 0.5) : stops[0] }
  }

  if (fill.pattern === 'none') {
    return undefined
  }

  const foreground = resolveColor(fill.fgColor as ExcelColor, palette) ?? '#000000'

  if (fill.pattern === 'solid') {
    return { rgb: foreground }
  }

  notes.add(NOTES.pattern)
  const background = resolveColor(fill.bgColor as ExcelColor, palette) ?? '#ffffff'

  return { rgb: mixed(foreground, background, PATTERN_DENSITY[fill.pattern] ?? 0.5) }
}

function borderStyle(border: Partial<Borders> | undefined, palette: Palette): UStyle['bd'] | undefined {
  if (!border) {
    return undefined
  }

  const sides: UStyle['bd'] = {}
  const side = (edge: { style?: string; color?: unknown } | undefined) => {
    const index = edge?.style ? BORDERS.indexOf(edge.style as (typeof BORDERS)[number]) : -1

    return index > 0 ? { s: index, cl: { rgb: resolveColor(edge!.color as ExcelColor, palette) ?? '#000000' } } : null
  }

  for (const [from, to] of [['top', 't'], ['right', 'r'], ['bottom', 'b'], ['left', 'l']] as const) {
    const found = side(border[from])

    if (found) {
      sides[to] = found
    }
  }

  const diagonal = side(border.diagonal)

  if (diagonal && border.diagonal?.down) {
    sides.tl_br = diagonal
  }

  if (diagonal && border.diagonal?.up) {
    sides.bl_tr = diagonal
  }

  return Object.keys(sides).length ? sides : undefined
}

function alignmentStyle(alignment: Partial<Alignment> | undefined, notes: StyleNotes): UStyle {
  const style: UStyle = {}

  if (!alignment) {
    return style
  }

  const horizontal = alignment.horizontal

  if (horizontal === 'left' || horizontal === 'center' || horizontal === 'right' || horizontal === 'justify' || horizontal === 'distributed') {
    style.ht = ALIGN[horizontal]
  } else if (horizontal === 'centerContinuous') {
    style.ht = ALIGN.center
    notes.add(NOTES.alignment)
  } else if (horizontal === 'fill') {
    style.ht = ALIGN.left
    notes.add(NOTES.alignment)
  }

  if (alignment.vertical === 'top' || alignment.vertical === 'bottom') {
    style.vt = VALIGN[alignment.vertical]
  } else if (alignment.vertical === 'middle') {
    style.vt = VALIGN.middle
  } else if (alignment.vertical === 'justify' || alignment.vertical === 'distributed') {
    style.vt = VALIGN.middle
    notes.add(NOTES.alignment)
  }

  if (alignment.wrapText) {
    style.tb = WRAP.wrap
  }

  if (alignment.shrinkToFit) {
    style.stf = 1
  }

  if (alignment.textRotation === 'vertical') {
    style.tr = { a: 0, v: 1 }
  } else if (typeof alignment.textRotation === 'number' && alignment.textRotation) {
    // ExcelJS turns counter-clockwise as positive; Univer turns clockwise.
    style.tr = { a: -alignment.textRotation }
  }

  if (alignment.indent && alignment.indent > 0) {
    const pixels = PADDING.l + alignment.indent * INDENT_PIXELS
    style.pd = style.ht === ALIGN.right ? { r: pixels } : { l: pixels }
  }

  return style
}

/**
 * An ExcelJS cell style as Univer's, without what the default style already says; null when
 * nothing is left. `formatCode` gives a number format as the file wrote it (ExcelJS drops its
 * backslash escapes, which can change what a format shows).
 */
export function styleFromExcel(style: Partial<Style> | undefined, base: BaseFont, palette: Palette, notes: StyleNotes, formatCode: (code: string) => string = (code) => code): UStyle | null {
  if (!style) {
    return null
  }

  const out: UStyle = { ...fontStyle(style.font, base, palette), ...alignmentStyle(style.alignment, notes) }
  const bg = fillStyle(style.fill, palette, notes)
  const bd = borderStyle(style.border, palette)

  if (bg) {
    out.bg = bg
  }

  if (bd) {
    out.bd = bd
  }

  if (style.numFmt && style.numFmt !== 'General') {
    out.n = { pattern: SHOWN_AS[style.numFmt] ?? formatCode(style.numFmt) }
  }

  return Object.keys(out).length ? out : null
}

const color = (rgb: string | null | undefined): { argb: string } | undefined => {
  const argb = argbOf(rgb)

  return argb ? { argb } : undefined
}

/** A Univer text style as an ExcelJS font: complete (name, size), as Excel writes every font. */
export function excelFont(style: UStyle, base: BaseFont): Partial<Font> {
  const font: Partial<Font> = { name: style.ff || base.name, size: style.fs || base.size }
  const fontColor = color(style.cl?.rgb ?? base.color)

  if (style.bl) {
    font.bold = true
  }

  if (style.it) {
    font.italic = true
  }

  if (style.ul?.s) {
    const kind = Object.entries(DECORATION).find(([, value]) => value === style.ul?.t)?.[0] as Font['underline'] | undefined
    font.underline = kind && kind !== 'single' ? kind : true
  }

  if (style.st?.s) {
    font.strike = true
  }

  if (style.va === BASELINE.subscript || style.va === BASELINE.superscript) {
    font.vertAlign = style.va === BASELINE.subscript ? 'subscript' : 'superscript'
  }

  if (fontColor) {
    font.color = fontColor
  }

  return font
}

/** Excel has one diagonal border style; Univer one per direction. */
export const differentDiagonals = (sides: UStyle['bd'] | undefined): boolean => Boolean(sides?.tl_br && sides.bl_tr && (sides.tl_br.s !== sides.bl_tr.s || sides.tl_br.cl?.rgb !== sides.bl_tr.cl?.rgb))

function excelBorder(sides: NonNullable<UStyle['bd']>): Partial<Borders> | undefined {
  const border: Partial<Borders> = {}
  const edge = (side: { s: number; cl?: { rgb?: string | null } } | null | undefined) =>
    side && side.s > 0 && BORDERS[side.s] ? { style: BORDERS[side.s] as Borders['top']['style'], color: color(side.cl?.rgb) ?? { argb: 'FF000000' } } : undefined

  for (const [from, to] of [['t', 'top'], ['r', 'right'], ['b', 'bottom'], ['l', 'left']] as const) {
    const found = edge(sides[from])

    if (found) {
      border[to] = found
    }
  }

  const down = edge(sides.tl_br)
  const up = edge(sides.bl_tr)

  if (down || up) {
    border.diagonal = { ...(down ?? up)!, up: Boolean(up), down: Boolean(down) }
  }

  return Object.keys(border).length ? border : undefined
}

function excelAlignment(style: UStyle): Partial<Alignment> | undefined {
  const alignment: Partial<Alignment> = {}
  const horizontal = Object.entries(ALIGN).find(([, value]) => value === style.ht)?.[0] ?? (style.ht === 5 ? 'justify' : undefined)
  const vertical = Object.entries(VALIGN).find(([, value]) => value === style.vt)?.[0]

  if (horizontal) {
    alignment.horizontal = horizontal as Alignment['horizontal']
  }

  if (vertical) {
    alignment.vertical = vertical as Alignment['vertical']
  }

  if (style.tb === WRAP.wrap) {
    alignment.wrapText = true
  }

  if (style.stf) {
    alignment.shrinkToFit = true
  }

  if (style.tr?.v) {
    alignment.textRotation = 'vertical'
  } else if (style.tr?.a) {
    alignment.textRotation = Math.max(-90, Math.min(90, -style.tr.a))
  }

  const padding = style.ht === ALIGN.right ? style.pd?.r : style.pd?.l
  const indent = padding !== undefined ? Math.round((padding - PADDING.l) / INDENT_PIXELS) : 0

  if (indent > 0) {
    alignment.indent = Math.min(250, indent)
  }

  return Object.keys(alignment).length ? alignment : undefined
}

/** A Univer cell style (over the sheet's default) as an ExcelJS style. */
export function excelStyle(style: UStyle | null | undefined, base: BaseFont): Partial<Style> {
  const out: Partial<Style> = { font: excelFont(style ?? {}, base) }

  if (!style) {
    return out
  }

  const bg = hexOf(style.bg?.rgb)

  if (bg) {
    out.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: argbOf(bg)! } }
  }

  const border = style.bd ? excelBorder(style.bd) : undefined

  if (border) {
    out.border = border
  }

  const alignment = excelAlignment(style)

  if (alignment) {
    out.alignment = alignment
  }

  if (style.n?.pattern) {
    out.numFmt = style.n.pattern
  }

  return out
}

/** Styles layered as Univer layers them: later ones win, field by field (borders side by side). */
export function composeStyles(...styles: (UStyle | null | undefined)[]): UStyle {
  const out: UStyle = {}

  for (const style of styles) {
    if (!style) {
      continue
    }

    for (const [key, value] of Object.entries(style) as [keyof UStyle, unknown][]) {
      if (value === undefined || value === null) {
        continue
      }

      Object.assign(out, { [key]: key === 'bd' ? { ...out.bd, ...(value as UStyle['bd']) } : value })
    }
  }

  return out
}
