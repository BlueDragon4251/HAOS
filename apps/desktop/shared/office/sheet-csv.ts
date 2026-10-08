import { type CsvLayout, parseCsv, serializeCsv } from './csv.ts'
import { CELL_TYPE, type CellMatrix, type CellSnapshot, cellsOf, hasContent, isStyled, newSheet, newWorkbook, type SheetSnapshot, type WorkbookSnapshot } from './workbook.ts'

/*
 * A CSV file as a one-sheet workbook and back. Numbers become numbers unless that would change
 * them (leading zeros, more digits than a number holds), TRUE and FALSE become true and false, and
 * a field starting with "=" is a formula, as spreadsheets read CSV. Saving writes the sheet in
 * front: each cell as it shows (a formula's result, a number in its format), and lists what a CSV
 * file cannot hold.
 */

const NUMBER = /^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$/

/** How a number shows in a number format ("1,200.50", "10/8/2026"); the renderer passes Univer's formatter. */
export type NumberFormatter = (value: number, pattern: string) => string

/** A field as a cell: a number when it reads back the same, a boolean, a formula, or text. */
export function cellFromField(field: string): CellSnapshot | null {
  if (field === '') {
    return null
  }

  if (field.startsWith('=') && field.length > 1) {
    return { f: field }
  }

  if (field === 'TRUE' || field === 'FALSE') {
    return { v: field === 'TRUE' ? 1 : 0, t: CELL_TYPE.boolean }
  }

  const digits = field.replace(/^[-+]/, '').replace(/[.eE].*$/, '')

  if (NUMBER.test(field) && !/^0\d/.test(digits) && digits.length <= 15) {
    return { v: Number(field), t: CELL_TYPE.number }
  }

  return { v: field, t: CELL_TYPE.string }
}

/** What a cell shows as CSV text: its value, or its formula's result; a number in `pattern` when there is a formatter. */
export function fieldFromCell(cell: CellSnapshot | undefined, pattern?: string | null, format?: NumberFormatter): string {
  if (!cell) {
    return ''
  }

  const value = cell.v

  if (cell.t === CELL_TYPE.boolean || typeof value === 'boolean') {
    return value === true || value === 1 || value === 'TRUE' || value === '1' ? 'TRUE' : 'FALSE'
  }

  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      return ''
    }

    if (pattern && format && pattern !== 'General' && pattern !== '@') {
      try {
        return format(value, pattern)
      } catch {
        // A format the formatter cannot read shows the plain number, as below.
      }
    }

    // Fifteen significant digits, as spreadsheets show them, so 0.1 + 0.2 is written as 0.3.
    return String(Number(value.toPrecision(15)))
  }

  if (value === undefined || value === null || value === '') {
    return cell.f && cell.v === undefined ? cell.f : ''
  }

  return String(value)
}

export function workbookFromCsv(text: string, options: { id: string; name: string }): { workbook: WorkbookSnapshot; layout: CsvLayout } {
  const { rows, ...layout } = parseCsv(text)
  const cellData: CellMatrix = {}
  let columns = 0

  rows.forEach((fields, row) => {
    columns = Math.max(columns, fields.length)

    fields.forEach((field, column) => {
      const cell = cellFromField(field)

      if (cell) {
        cellData[row] ??= {}
        cellData[row][column] = cell
      }
    })
  })

  const sheet = newSheet('sheet-1', options.name.slice(0, 31) || 'Sheet1', cellData, { rows: rows.length, columns })

  return { workbook: newWorkbook(options.id, options.name, [sheet]), layout }
}

/** The sheet a CSV file gets: the one asked for, else the first. */
function sheetToWrite(workbook: WorkbookSnapshot, sheetId?: string) {
  return (sheetId && workbook.sheets[sheetId]) || workbook.sheets[workbook.sheetOrder[0]]
}

/** The number format a cell shows in: its own, else its row's, else its column's (Univer's order). */
export function patternOf(workbook: WorkbookSnapshot, sheet: SheetSnapshot, row: number, column: number, cell: CellSnapshot | undefined): string | null {
  const resolve = (style: unknown): { n?: { pattern?: string } | null } | null => (typeof style === 'string' ? ((workbook.styles?.[style] as { n?: { pattern?: string } } | undefined) ?? null) : ((style as { n?: { pattern?: string } } | null) ?? null))
  const lines = (data: unknown, index: number) => resolve(((data ?? {}) as Record<number, { s?: unknown }>)[index]?.s)

  return resolve(cell?.s)?.n?.pattern ?? lines(sheet.columnData, column)?.n?.pattern ?? lines(sheet.rowData, row)?.n?.pattern ?? null
}

export function csvFromWorkbook(workbook: WorkbookSnapshot, options: { sheetId?: string; layout?: Partial<CsvLayout>; format?: NumberFormatter } = {}): { text: string; losses: string[] } {
  const sheet = sheetToWrite(workbook, options.sheetId)
  const rows: string[][] = []
  let formulas = false
  let styled = false

  for (const { row, column, cell } of sheet ? cellsOf(sheet) : []) {
    formulas ||= Boolean(cell.f || cell.si)
    styled ||= isStyled(cell, workbook.styles ?? {})

    if (!hasContent(cell)) {
      continue
    }

    while (rows.length <= row) {
      rows.push([])
    }

    const fields = rows[row]

    while (fields.length < column) {
      fields.push('')
    }

    fields[column] = fieldFromCell(cell, options.format ? patternOf(workbook, sheet, row, column, cell) : null, options.format)
  }

  const others = workbook.sheetOrder.filter((id) => id !== sheet?.id && [...cellsOf(workbook.sheets[id] ?? { cellData: {} })].some(({ cell }) => hasContent(cell)))
  const losses = [
    ...(others.length ? [`Only the sheet “${sheet?.name}” is saved: a CSV file holds one sheet (${others.length === 1 ? 'one other sheet has' : `${others.length} other sheets have`} data).`] : []),
    ...(formulas ? ['Formulas are saved as their results.'] : []),
    ...(styled ? ['Formatting (fonts, colours, borders and number formats) is not saved; numbers are saved as they show.'] : []),
    ...(sheet?.mergeData?.length ? ['Merged cells are saved as separate cells.'] : [])
  ]

  return { text: serializeCsv(rows, options.layout), losses }
}
