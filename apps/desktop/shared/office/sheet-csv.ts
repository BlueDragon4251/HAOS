import { type CsvLayout, parseCsv, serializeCsv } from './csv.ts'
import { CELL_TYPE, type CellMatrix, type CellSnapshot, cellsOf, hasContent, isStyled, newSheet, newWorkbook, type WorkbookSnapshot } from './workbook.ts'

/*
 * A CSV file as a one-sheet workbook and back. Numbers become numbers unless that would change
 * them (leading zeros, more digits than a number holds), and a field starting with "=" is a
 * formula, as spreadsheets read CSV. Saving writes the results of formulas, and lists what a CSV
 * file cannot hold.
 */

const NUMBER = /^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$/

/** A field as a cell: a number when it reads back the same, a formula, or text. */
export function cellFromField(field: string): CellSnapshot | null {
  if (field === '') {
    return null
  }

  if (field.startsWith('=') && field.length > 1) {
    return { f: field }
  }

  const digits = field.replace(/^[-+]/, '').replace(/[.eE].*$/, '')

  if (NUMBER.test(field) && !/^0\d/.test(digits) && digits.length <= 15) {
    return { v: Number(field), t: CELL_TYPE.number }
  }

  return { v: field, t: CELL_TYPE.string }
}

/** What a cell shows as CSV text: its value, or its formula's result. */
export function fieldFromCell(cell: CellSnapshot | undefined): string {
  if (!cell) {
    return ''
  }

  const value = cell.v

  if (typeof value === 'number') {
    // Fifteen significant digits, as spreadsheets show them, so 0.1 + 0.2 is written as 0.3.
    return Number.isFinite(value) ? String(Number(value.toPrecision(15))) : ''
  }

  if (typeof value === 'boolean') {
    return value ? 'TRUE' : 'FALSE'
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

export function csvFromWorkbook(workbook: WorkbookSnapshot, options: { sheetId?: string; layout?: Partial<CsvLayout> } = {}): { text: string; losses: string[] } {
  const sheet = sheetToWrite(workbook, options.sheetId)
  const rows: string[][] = []
  let formulas = false
  let styled = false

  for (const { row, column, cell } of sheet ? cellsOf(sheet) : []) {
    formulas ||= Boolean(cell.f)
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

    fields[column] = fieldFromCell(cell)
  }

  const others = workbook.sheetOrder.filter((id) => id !== sheet?.id && [...cellsOf(workbook.sheets[id] ?? { cellData: {} })].some(({ cell }) => hasContent(cell)))
  const losses = [
    ...(others.length ? [`Only the sheet “${sheet?.name}” is saved: a CSV file holds one sheet (${others.length === 1 ? 'one other sheet has' : `${others.length} other sheets have`} data).`] : []),
    ...(formulas ? ['Formulas are saved as their results.'] : []),
    ...(styled ? ['Formatting (fonts, colours, borders and number formats) is not saved.'] : []),
    ...(sheet?.mergeData?.length ? ['Merged cells are saved as separate cells.'] : [])
  ]

  return { text: serializeCsv(rows, options.layout), losses }
}
