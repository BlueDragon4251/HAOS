/*
 * CSV as spreadsheets write it (RFC 4180): fields split by a delimiter and quoted when they hold
 * the delimiter, a quote or a line break, with quotes inside doubled. The delimiter, line ending
 * and byte-order mark a file had are kept, so saving it again changes only what was edited.
 */

export type CsvDelimiter = ',' | ';' | '\t'

export interface CsvLayout {
  delimiter: CsvDelimiter
  eol: '\n' | '\r\n'
  bom: boolean
}

export interface CsvTable extends CsvLayout {
  rows: string[][]
}

const DELIMITERS: readonly CsvDelimiter[] = [',', ';', '\t']

/** How many delimiters each of the first lines has, outside quotes. */
function counts(text: string, delimiter: string, lines = 10): number[] {
  const out: number[] = []
  let count = 0
  let quoted = false

  for (let i = 0; i < text.length && out.length < lines; i++) {
    const char = text[i]

    if (char === '"') {
      quoted = !quoted
    } else if (!quoted && char === delimiter) {
      count++
    } else if (!quoted && char === '\n') {
      out.push(count)
      count = 0
    }
  }

  if (count > 0 || !out.length) {
    out.push(count)
  }

  return out
}

/** The delimiter a file uses: the one found on every one of its first lines, most often; a comma when none is. */
export function sniffDelimiter(text: string): CsvDelimiter {
  let best: CsvDelimiter = ','
  let bestScore = 0

  for (const delimiter of DELIMITERS) {
    const found = counts(text, delimiter)
    const least = Math.min(...found)

    if (least > 0 && least > bestScore) {
      best = delimiter
      bestScore = least
    }
  }

  return best
}

export function parseCsv(input: string, delimiter?: CsvDelimiter): CsvTable {
  const bom = input.startsWith('\uFEFF')
  const text = bom ? input.slice(1) : input
  const eol = /\r\n/.test(text) ? '\r\n' : '\n'
  const split = delimiter ?? sniffDelimiter(text)
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  let i = 0

  while (i < text.length) {
    const char = text[i]

    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        field += '"'
        i += 2
        continue
      }

      if (char === '"') {
        quoted = false
      } else {
        field += char
      }

      i++
      continue
    }

    if (char === '"' && field === '') {
      quoted = true
    } else if (char === split) {
      row.push(field)
      field = ''
    } else if (char === '\n' || char === '\r') {
      row.push(field)
      rows.push(row)
      row = []
      field = ''

      if (char === '\r' && text[i + 1] === '\n') {
        i++
      }
    } else {
      field += char
    }

    i++
  }

  // A last line without its line break still counts; the line break that ends the file adds no row.
  if (field !== '' || row.length) {
    row.push(field)
    rows.push(row)
  }

  return { rows, delimiter: split, eol, bom }
}

const needsQuotes = (field: string, delimiter: string): boolean => field.includes(delimiter) || field.includes('"') || field.includes('\n') || field.includes('\r') || /^\s|\s$/.test(field)

export function serializeCsv(rows: readonly (readonly string[])[], layout: Partial<CsvLayout> = {}): string {
  const delimiter = layout.delimiter ?? ','
  const eol = layout.eol ?? '\n'
  const lines = rows.map((row) => row.map((field) => (needsQuotes(field, delimiter) ? `"${field.replace(/"/g, '""')}"` : field)).join(delimiter))

  return `${layout.bom ? '\uFEFF' : ''}${lines.join(eol)}${lines.length ? eol : ''}`
}
