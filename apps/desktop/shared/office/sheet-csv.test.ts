import { describe, expect, it } from 'vitest'
import { cellFromField, csvFromWorkbook, fieldFromCell, workbookFromCsv } from './sheet-csv.ts'
import { CELL_TYPE, newSheet, newWorkbook } from './workbook.ts'

describe('cellFromField', () => {
  it('reads numbers that read back the same, formulas, and text', () => {
    expect(cellFromField('42')).toEqual({ v: 42, t: CELL_TYPE.number })
    expect(cellFromField('-3.5e2')).toEqual({ v: -350, t: CELL_TYPE.number })
    expect(cellFromField('=SUM(A1:A3)')).toEqual({ f: '=SUM(A1:A3)' })
    expect(cellFromField('Rent')).toEqual({ v: 'Rent', t: CELL_TYPE.string })
    expect(cellFromField('')).toBeNull()
  })

  it('keeps as text what a number would change', () => {
    expect(cellFromField('007')).toEqual({ v: '007', t: CELL_TYPE.string })
    expect(cellFromField('4111111111111111')).toEqual({ v: '4111111111111111', t: CELL_TYPE.string })
    expect(cellFromField('=')).toEqual({ v: '=', t: CELL_TYPE.string })
  })
})

describe('fieldFromCell', () => {
  it('writes values, formula results and booleans', () => {
    expect(fieldFromCell({ v: 0.1 + 0.2, t: CELL_TYPE.number })).toBe('0.3')
    expect(fieldFromCell({ f: '=A1*2', v: 84 })).toBe('84')
    expect(fieldFromCell({ v: true })).toBe('TRUE')
    expect(fieldFromCell({ f: '=A1' })).toBe('=A1')
    expect(fieldFromCell(undefined)).toBe('')
  })
})

describe('workbookFromCsv and csvFromWorkbook', () => {
  it('round-trips a file with its layout', () => {
    const text = 'Item;Cost\r\nRent;1200\r\n"Food; drinks";310.5\r\n'
    const { workbook, layout } = workbookFromCsv(text, { id: 'book', name: 'Budget' })
    const sheet = workbook.sheets[workbook.sheetOrder[0]]

    expect(layout).toEqual({ delimiter: ';', eol: '\r\n', bom: false })
    expect(sheet.cellData[1][1]).toEqual({ v: 1200, t: CELL_TYPE.number })
    expect(sheet.rowCount).toBeGreaterThanOrEqual(1000)
    expect(csvFromWorkbook(workbook, { layout })).toEqual({ text, losses: [] })
  })

  it('lists what a CSV file cannot keep', () => {
    const first = newSheet('a', 'Totals', { 0: { 0: { v: 2, s: 'bold' }, 1: { f: '=A1*2', v: 4 } } })
    const second = newSheet('b', 'Notes', { 0: { 0: { v: 'kept elsewhere' } } })
    const { text, losses } = csvFromWorkbook(newWorkbook('book', 'Book', [first, second]))

    expect(text).toBe('2,4\n')
    expect(losses).toEqual([
      'Only the sheet “Totals” is saved: a CSV file holds one sheet (one other sheet has data).',
      'Formulas are saved as their results.',
      'Formatting (fonts, colours, borders and number formats) is not saved.'
    ])
  })

  it('writes the sheet it is asked for, with gaps as empty fields', () => {
    const sheet = newSheet('s', 'S', { 0: { 2: { v: 'c' } }, 2: { 0: { v: 'a' } } })

    expect(csvFromWorkbook(newWorkbook('book', 'Book', [newSheet('t', 'T'), sheet]), { sheetId: 's' }).text).toBe(',,c\n\na\n')
  })
})
