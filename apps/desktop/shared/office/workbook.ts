/*
 * The parts of a Univer workbook snapshot Herald's converters read and write. They are plain data
 * (Univer's own types describe the same shapes), so converters run anywhere, tests included.
 */

/** Univer's cell value types. */
export const CELL_TYPE = { string: 1, number: 2, boolean: 3, text: 4 } as const

export interface CellSnapshot {
  v?: string | number | boolean | null
  f?: string | null
  t?: number | null
  /** A style id in the workbook's styles, or a style itself. */
  s?: string | Record<string, unknown> | null
  [key: string]: unknown
}

export type CellMatrix = Record<number, Record<number, CellSnapshot>>

export interface SheetSnapshot {
  id: string
  name: string
  rowCount: number
  columnCount: number
  cellData: CellMatrix
  mergeData?: unknown[]
  [key: string]: unknown
}

export interface WorkbookSnapshot {
  id: string
  name: string
  appVersion: string
  locale: string
  styles: Record<string, unknown>
  sheetOrder: string[]
  sheets: Record<string, SheetSnapshot>
  [key: string]: unknown
}

/** The smallest sheet Herald shows, so a short file still has room to grow. */
const MIN_ROWS = 1000
const MIN_COLUMNS = 26

export function newSheet(id: string, name: string, cellData: CellMatrix = {}, size: { rows?: number; columns?: number } = {}): SheetSnapshot {
  return { id, name, rowCount: Math.max(MIN_ROWS, (size.rows ?? 0) + 100), columnCount: Math.max(MIN_COLUMNS, (size.columns ?? 0) + 10), cellData }
}

export function newWorkbook(id: string, name: string, sheets: SheetSnapshot[] = [newSheet('sheet-1', 'Sheet1')]): WorkbookSnapshot {
  return { id, name, appVersion: '1.0.3', locale: 'enUS', styles: {}, sheetOrder: sheets.map((sheet) => sheet.id), sheets: Object.fromEntries(sheets.map((sheet) => [sheet.id, sheet])) }
}

/** The cells of a sheet in row and column order, skipping empty rows. */
export function* cellsOf(sheet: Pick<SheetSnapshot, 'cellData'>): Generator<{ row: number; column: number; cell: CellSnapshot }> {
  for (const row of Object.keys(sheet.cellData ?? {}).map(Number).sort((a, b) => a - b)) {
    const columns = sheet.cellData[row] ?? {}

    for (const column of Object.keys(columns).map(Number).sort((a, b) => a - b)) {
      yield { row, column, cell: columns[column] }
    }
  }
}

/** Whether a cell shows anything: a value or a formula. */
export const hasContent = (cell: CellSnapshot | undefined): boolean => Boolean(cell) && ((cell!.v !== undefined && cell!.v !== null && cell!.v !== '') || Boolean(cell!.f))

const isEmptyStyle = (style: unknown): boolean => !style || (typeof style === 'object' && Object.keys(style).length === 0)

/** Whether a cell has any formatting of its own (a style that sets something). */
export function isStyled(cell: CellSnapshot, styles: Record<string, unknown>): boolean {
  const style = typeof cell.s === 'string' ? styles[cell.s] : cell.s

  return !isEmptyStyle(style)
}

const sameColor = (a: unknown, b: string): boolean => typeof a === 'string' && a.toLowerCase() === b.toLowerCase()

function withoutColor(style: Record<string, unknown>, automatic: string): Record<string, unknown> {
  const color = style.cl as { rgb?: string } | undefined

  if (!color || !sameColor(color.rgb, automatic)) {
    return style
  }

  const { cl: _automatic, ...rest } = style

  return rest
}

/**
 * The workbook without the text colour Univer's cell editor gives what is typed: the theme's
 * "automatic" colour, written out as a colour. It means no colour, and a saved file says so.
 */
export function withoutAutomaticColor(workbook: WorkbookSnapshot, automatic: string): WorkbookSnapshot {
  const styles: Record<string, unknown> = {}
  const emptied = new Set<string>()

  for (const [id, style] of Object.entries(workbook.styles ?? {})) {
    const next = style && typeof style === 'object' ? withoutColor(style as Record<string, unknown>, automatic) : style

    if (isEmptyStyle(next)) {
      emptied.add(id)
    } else {
      styles[id] = next
    }
  }

  const sheets: Record<string, SheetSnapshot> = {}

  for (const [id, sheet] of Object.entries(workbook.sheets)) {
    const cellData: CellMatrix = {}

    for (const [row, columns] of Object.entries(sheet.cellData ?? {})) {
      cellData[Number(row)] = {}

      for (const [column, cell] of Object.entries(columns)) {
        const style = typeof cell.s === 'string' ? (emptied.has(cell.s) ? null : cell.s) : cell.s ? withoutColor(cell.s, automatic) : cell.s
        const { s: _style, ...rest } = cell
        cellData[Number(row)][Number(column)] = isEmptyStyle(style) ? rest : { ...rest, s: style }
      }
    }

    sheets[id] = { ...sheet, cellData }
  }

  return { ...workbook, styles, sheets }
}
