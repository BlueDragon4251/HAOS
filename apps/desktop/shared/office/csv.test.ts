import { describe, expect, it } from 'vitest'
import { decodeCsv, encodeCsv, parseCsv, serializeCsv, sniffDelimiter } from './csv.ts'

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

  it('reads a delimiter at the end, old Mac line endings, text after a closing quote and an unclosed quote', () => {
    expect(parseCsv('a,b,\n').rows).toEqual([['a', 'b', '']])
    expect(parseCsv('a,b\r1,2\r').rows).toEqual([['a', 'b'], ['1', '2']])
    expect(parseCsv('"5" inches,x\n').rows).toEqual([['5 inches', 'x']])
    expect(parseCsv('a,"open\nline').rows).toEqual([['a', 'open\nline']])
  })

  it('reads a large file quickly', () => {
    const line = '12345,"Smith, Jo",some words here,3.14159,TRUE\n'
    const text = line.repeat(100000)
    const started = performance.now()
    const { rows } = parseCsv(text)

    expect(rows).toHaveLength(100000)
    expect(rows[99999]).toEqual(['12345', 'Smith, Jo', 'some words here', '3.14159', 'TRUE'])
    expect(performance.now() - started).toBeLessThan(2000)
  })
})

describe('decodeCsv and encodeCsv', () => {
  it('keeps a UTF-8 byte-order mark, so saving writes it again', () => {
    const bytes = new Uint8Array([0xef, 0xbb, 0xbf, ...new TextEncoder().encode('café,1\n')])
    const { text, encoding } = decodeCsv(bytes)
    const table = parseCsv(text)

    expect(encoding).toBe('utf-8')
    expect(table).toMatchObject({ bom: true, rows: [['café', '1']] })
    expect(encodeCsv(serializeCsv(table.rows, table), encoding)).toEqual(bytes)
  })

  it('reads UTF-16 with and without a byte-order mark, and writes it back the same', () => {
    const marked = encodeCsv('\uFEFFnom\tprix\ncafé\t2\n', 'utf-16le')
    const plain = encodeCsv('a,b\n1,2\n', 'utf-16be')

    expect(Array.from(marked.slice(0, 4))).toEqual([0xff, 0xfe, 0x6e, 0x00])
    expect(decodeCsv(marked)).toMatchObject({ encoding: 'utf-16le', text: '\uFEFFnom\tprix\ncafé\t2\n' })
    expect(parseCsv(decodeCsv(marked).text)).toMatchObject({ delimiter: '\t', bom: true, rows: [['nom', 'prix'], ['café', '2']] })
    expect(decodeCsv(plain)).toMatchObject({ encoding: 'utf-16be', text: 'a,b\n1,2\n' })
  })

  it('reads an older file as Windows-1252, with a note', () => {
    expect(decodeCsv(new Uint8Array([0x63, 0x61, 0x66, 0xe9]))).toMatchObject({ text: 'café', encoding: 'utf-8', notes: [expect.stringContaining('Windows-1252')] })
  })
})

describe('sniffDelimiter', () => {
  it('finds semicolons, tabs and pipes, and ignores delimiters inside quotes', () => {
    expect(sniffDelimiter('a;b;c\n1;2;3\n')).toBe(';')
    expect(sniffDelimiter('a\tb\n1\t2\n')).toBe('\t')
    expect(sniffDelimiter('a|b|c\n1|2|3\n')).toBe('|')
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
