import fs from 'node:fs'
import ExcelJS from 'exceljs'
import { describe, expect, it } from 'vitest'
import { workbookFromXlsx } from './read.ts'
import { xlsxFromWorkbook } from './write.ts'

/** 2,500 rows of 20 columns: numbers, text, dates, a formula in every fifth column, and a few styles. */
async function largeWorkbook(): Promise<Uint8Array> {
  const book = new ExcelJS.Workbook()
  const sheet = book.addWorksheet('Large')
  const money = { numFmt: '#,##0.00' }
  const header = { font: { bold: true }, fill: { type: 'pattern' as const, pattern: 'solid' as const, fgColor: { argb: 'FFDDEBF7' } } }

  for (let row = 1; row <= 2500; row++) {
    const values: ExcelJS.CellValue[] = []

    for (let column = 1; column <= 20; column++) {
      values.push(column % 5 === 0 ? { formula: `SUM(A${row}:${String.fromCharCode(64 + column - 1)}${row})`, result: row * column } : column % 3 === 0 ? `Item ${row}-${column}` : column === 7 ? new Date(Date.UTC(2026, 0, 1 + (row % 365))) : row * column + 0.5)
    }

    const added = sheet.addRow(values)

    if (row === 1) {
      added.eachCell((cell) => Object.assign(cell, header))
    } else {
      added.getCell(2).numFmt = money.numFmt
    }
  }

  return new Uint8Array((await book.xlsx.writeBuffer()) as ArrayBuffer)
}

describe('a 50,000-cell workbook', () => {
  it('opens and saves in a few seconds', async () => {
    const bytes = await largeWorkbook()
    const started = performance.now()
    const { workbook } = await workbookFromXlsx(bytes, { id: 'large', name: 'Large' })
    const read = performance.now() - started
    const cells = Object.values(workbook.sheets[workbook.sheetOrder[0]].cellData).reduce((sum, row) => sum + Object.keys(row).length, 0)
    const writing = performance.now()
    const { bytes: written } = await xlsxFromWorkbook(workbook)
    const write = performance.now() - writing

    if (process.env.SHEETS_PERF_FILE) {
      fs.writeFileSync(process.env.SHEETS_PERF_FILE, JSON.stringify({ cells, readMs: Math.round(read), writeMs: Math.round(write), inBytes: bytes.byteLength, outBytes: written.byteLength }))
    }

    expect(cells).toBe(50000)
    expect(read).toBeLessThan(15000)
    expect(write).toBeLessThan(15000)
  }, 60000)
})
