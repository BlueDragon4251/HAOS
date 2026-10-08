import { describe, expect, it } from 'vitest'
import { parseCsv, serializeCsv, sniffDelimiter } from './csv.ts'

describe('parseCsv', () => {
  it('reads quoted fields with delimiters, doubled quotes and line breaks', () => {
    const table = parseCsv('name,notes\n"Smith, Jo","said ""hi""\nthen left"\nAl,\n')

    expect(table.rows).toEqual([
      ['name', 'notes'],
      ['Smith, Jo', 'said "hi"\nthen left'],
      ['Al', '']
    ])
    expect(table.eol).toBe('\n')
  })

  it('keeps a last line without a line break and the CRLF endings and BOM of the file', () => {
    const table = parseCsv('\uFEFFa,b\r\n1,2')

    expect(table.rows).toEqual([
      ['a', 'b'],
      ['1', '2']
    ])
    expect(table.eol).toBe('\r\n')
    expect(table.bom).toBe(true)
  })

  it('keeps empty lines in the middle as rows', () => {
    expect(parseCsv('a\n\nb\n').rows).toEqual([['a'], [''], ['b']])
  })

  it('reads an empty file as no rows', () => {
    expect(parseCsv('').rows).toEqual([])
  })
})

describe('sniffDelimiter', () => {
  it('finds semicolons and tabs, and ignores delimiters inside quotes', () => {
    expect(sniffDelimiter('a;b;c\n1;2;3\n')).toBe(';')
    expect(sniffDelimiter('a\tb\n1\t2\n')).toBe('\t')
    expect(sniffDelimiter('"x;y",b\n"1;2",3\n')).toBe(',')
    expect(sniffDelimiter('single column\nvalue\n')).toBe(',')
  })
})

describe('serializeCsv', () => {
  it('quotes only what needs quotes and round-trips', () => {
    const rows = [
      ['name', 'notes'],
      ['Smith, Jo', 'said "hi"'],
      [' padded', 'multi\nline']
    ]
    const text = serializeCsv(rows)

    expect(text).toBe('name,notes\n"Smith, Jo","said ""hi"""\n" padded","multi\nline"\n')
    expect(parseCsv(text).rows).toEqual(rows)
  })

  it('writes the layout it is given', () => {
    expect(serializeCsv([['a', 'b;c']], { delimiter: ';', eol: '\r\n', bom: true })).toBe('\uFEFFa;"b;c"\r\n')
    expect(serializeCsv([])).toBe('')
  })
})
