/*
 * CSV as spreadsheets write it (RFC 4180): fields split by a delimiter and quoted when they hold
 * the delimiter, a quote or a line break, with quotes inside doubled. The delimiter, line ending,
 * byte-order mark and encoding a file had are kept, so saving it again changes only what was edited.
 */

export type CsvDelimiter = ',' | ';' | '\t' | '|'

export type CsvEncoding = 'utf-8' | 'utf-16le' | 'utf-16be'

export interface CsvLayout {
  delimiter: CsvDelimiter
  eol: '\n' | '\r\n'
  bom: boolean
  encoding?: CsvEncoding
}

export interface CsvTable extends CsvLayout {
  rows: string[][]
}

const DELIMITERS: readonly CsvDelimiter[] = [',', ';', '\t', '|']
const QUOTE = 34
const LF = 10
const CR = 13

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

/** Where an unquoted field ends: at the delimiter, a line break or the end. */
function fieldEnd(text: string, from: number, separator: number): number {
  for (let at = from; at < text.length; at++) {
    const code = text.charCodeAt(at)

    if (code === separator || code === LF || code === CR) {
      return at
    }
  }

  return text.length
}

export function parseCsv(input: string, delimiter?: CsvDelimiter): CsvTable {
  const bom = input.charCodeAt(0) === 0xfeff
  const text = bom ? input.slice(1) : input
  const eol = text.includes('\r\n') ? '\r\n' : '\n'
  const split = delimiter ?? sniffDelimiter(text)
  const separator = split.charCodeAt(0)
  const rows: string[][] = []
  let row: string[] = []
  let i = 0

  while (i < text.length) {
    let value = ''

    if (text.charCodeAt(i) === QUOTE) {
      let from = i + 1

      for (;;) {
        const quote = text.indexOf('"', from)

        if (quote < 0) {
          value += text.slice(from)
          i = text.length
          break
        }

        if (text.charCodeAt(quote + 1) === QUOTE) {
          value += text.slice(from, quote + 1)
          from = quote + 2
          continue
        }

        value += text.slice(from, quote)
        i = quote + 1
        break
      }
    }

    // An unquoted field, or what follows a closing quote up to the delimiter, as it is.
    const end = fieldEnd(text, i, separator)
    value += text.slice(i, end)
    i = end
    row.push(value)

    if (i >= text.length) {
      rows.push(row)
      row = []
      break
    }

    if (text.charCodeAt(i) === separator) {
      i++

      // A delimiter at the very end leaves one more, empty, field.
      if (i >= text.length) {
        row.push('')
        rows.push(row)
        row = []
      }

      continue
    }

    rows.push(row)
    row = []
    i += text.charCodeAt(i) === CR && text.charCodeAt(i + 1) === LF ? 2 : 1
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

/** UTF-16 without a byte-order mark shows as a zero byte beside most characters of Latin text. */
function utf16Without(bytes: Uint8Array): CsvEncoding | null {
  const sample = bytes.subarray(0, 4096)
  let even = 0
  let odd = 0

  for (let i = 0; i < sample.length; i++) {
    if (sample[i] === 0) {
      if (i % 2) {
        odd++
      } else {
        even++
      }
    }
  }

  const half = sample.length / 2

  return odd > half * 0.4 && odd > even * 4 ? 'utf-16le' : even > half * 0.4 && even > odd * 4 ? 'utf-16be' : null
}

/**
 * A CSV file's text and encoding: UTF-8 (a byte-order mark kept as the text's first character, so
 * saving keeps it), UTF-16 with or without a mark, or else Windows-1252, which saving changes.
 */
export function decodeCsv(bytes: Uint8Array): { text: string; encoding: CsvEncoding; notes: string[] } {
  const wide = bytes[0] === 0xff && bytes[1] === 0xfe ? 'utf-16le' : bytes[0] === 0xfe && bytes[1] === 0xff ? 'utf-16be' : utf16Without(bytes)

  if (wide) {
    return { text: new TextDecoder(wide, { ignoreBOM: true }).decode(bytes), encoding: wide, notes: [] }
  }

  try {
    return { text: new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes), encoding: 'utf-8', notes: [] }
  } catch {
    return { text: new TextDecoder('windows-1252').decode(bytes), encoding: 'utf-8', notes: ['The file is not in UTF-8; Herald reads it as Windows-1252 and saves it as UTF-8.'] }
  }
}

/** CSV text as bytes in an encoding (a byte-order mark at the text's start becomes the encoding's). */
export function encodeCsv(text: string, encoding: CsvEncoding = 'utf-8'): Uint8Array {
  if (encoding === 'utf-8') {
    return new TextEncoder().encode(text)
  }

  const bytes = new Uint8Array(text.length * 2)
  const [low, high] = encoding === 'utf-16le' ? [0, 1] : [1, 0]

  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i)
    bytes[i * 2 + low] = code & 0xff
    bytes[i * 2 + high] = code >> 8
  }

  return bytes
}
