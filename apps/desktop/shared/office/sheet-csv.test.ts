import { describe, expect, it } from 'vitest'
import { cellFromField, csvFromWorkbook, fieldFromCell, workbookFromCsv } from './sheet-csv.ts'
import { CELL_TYPE, isStyled, newSheet, newWorkbook, withoutAutomaticColor } from './workbook.ts'

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
    const workbook = newWorkbook('book', 'Book', [first, second])
    workbook.styles = { bold: { bl: 1 } }
    const { text, losses } = csvFromWorkbook(workbook)

    expect(text).toBe('2,4\n')
    expect(losses).toEqual([
      'Only the sheet “Totals” is saved: a CSV file holds one sheet (one other sheet has data).',
      'Formulas are saved as their results.',
      'Formatting (fonts, colours, borders and number formats) is not saved; numbers are saved as they show.'
    ])
  })

  it('does not count the automatic colour of typed cells as formatting', () => {
    const workbook = newWorkbook('book', 'Book', [newSheet('s', 'S', { 0: { 0: { v: 42, s: 'typed' }, 1: { v: 'red', s: 'red' }, 2: { v: 'inline', s: { cl: { rgb: '#0C1431' } } } } })])
    workbook.styles = { typed: { cl: { rgb: '#0c1431' } }, red: { cl: { rgb: '#ff0000' }, bl: 1 } }
    const plain = withoutAutomaticColor(workbook, '#0c1431')
    const cells = plain.sheets.s.cellData[0]

    expect(plain.styles).toEqual({ red: { cl: { rgb: '#ff0000' }, bl: 1 } })
    expect(cells[0]).toEqual({ v: 42 })
    expect(cells[1].s).toBe('red')
    expect(cells[2]).toEqual({ v: 'inline' })
    expect(isStyled(cells[1], plain.styles)).toBe(true)
    expect(isStyled({ v: 1, s: 'gone' }, plain.styles)).toBe(false)
    expect(csvFromWorkbook(withoutAutomaticColor(newWorkbook('b', 'B', [newSheet('s', 'S', { 0: { 0: { v: 1, s: 'typed' } } })]), '#0c1431')).losses).toEqual([])
  })

  it('writes the sheet it is asked for, with gaps as empty fields', () => {
    const sheet = newSheet('s', 'S', { 0: { 2: { v: 'c' } }, 2: { 0: { v: 'a' } } })

    expect(csvFromWorkbook(newWorkbook('book', 'Book', [newSheet('t', 'T'), sheet]), { sheetId: 's' }).text).toBe(',,c\n\na\n')
  })

  it('reads TRUE and FALSE as booleans and writes booleans back as words', () => {
    expect(cellFromField('TRUE')).toEqual({ v: 1, t: CELL_TYPE.boolean })
    expect(cellFromField('true')).toEqual({ v: 'true', t: CELL_TYPE.string })
    expect(fieldFromCell({ v: 0, t: CELL_TYPE.boolean })).toBe('FALSE')
    expect(csvFromWorkbook(workbookFromCsv('a,TRUE,FALSE\n', { id: 'b', name: 'B' }).workbook).text).toBe('a,TRUE,FALSE\n')
  })

  it('writes numbers as they show in their format, from the cell, its column or its row', () => {
    const sheet = newSheet('s', 'S', { 0: { 0: { v: 46303.5, s: 'date' }, 1: { v: 1200.5 }, 2: { v: 7 } }, 1: { 2: { v: 0.25, s: 'percent' } } })
    sheet.columnData = { 1: { s: 'money' } }
    const workbook = { ...newWorkbook('b', 'B', [sheet]), styles: { date: { n: { pattern: 'yyyy-mm-dd' } }, money: { n: { pattern: '#,##0.00' } }, percent: { n: { pattern: '0%' } } } }
    const shown: Record<string, string> = { 'yyyy-mm-dd': '2026-10-08', '#,##0.00': '1,200.50', '0%': '25%' }
    const format = (_value: number, pattern: string) => shown[pattern]

    expect(csvFromWorkbook(workbook, { format }).text).toBe('2026-10-08,"1,200.50",7\n,,25%\n')
    expect(csvFromWorkbook(workbook).text).toBe('46303.5,1200.5,7\n,,0.25\n')
  })
})
