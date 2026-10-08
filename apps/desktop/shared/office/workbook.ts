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
