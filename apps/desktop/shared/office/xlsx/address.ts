/* A1 references as Excel writes them, and the zero-based ranges Univer keeps. */

export interface CellRange {
  startRow: number
  startColumn: number
  endRow: number
  endColumn: number
}

/** The largest sheet Excel has: 1,048,576 rows by 16,384 columns (XFD). */
export const MAX_ROWS = 1048576
export const MAX_COLUMNS = 16384

export function columnName(index: number): string {
  let name = ''

  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    name = String.fromCharCode(65 + ((n - 1) % 26)) + name
  }

  return name
}

export function columnIndex(name: string): number {
  let index = 0

  for (const char of name.toUpperCase()) {
    index = index * 26 + (char.charCodeAt(0) - 64)
  }

  return index - 1
}

export const cellName = (row: number, column: number): string => `${columnName(column)}${row + 1}`

/** "B3" as row 2, column 1 (dollars allowed); null for anything else. */
export function parseCell(ref: string): { row: number; column: number } | null {
  const match = /^\$?([A-Za-z]{1,3})\$?(\d{1,7})$/.exec(ref.trim())

  if (!match) {
    return null
  }

  const row = Number(match[2]) - 1
  const column = columnIndex(match[1])

  return row >= 0 && row < MAX_ROWS && column < MAX_COLUMNS ? { row, column } : null
}

/** "A1:C9", "B2", "A:C" or "3:5" as a range; null for anything else. */
export function parseRange(ref: string): CellRange | null {
  const [first, second = first] = ref.trim().split(':')
  const a = parseCell(first)
  const b = parseCell(second)

  if (a && b) {
    return { startRow: Math.min(a.row, b.row), startColumn: Math.min(a.column, b.column), endRow: Math.max(a.row, b.row), endColumn: Math.max(a.column, b.column) }
  }

  const columns = /^\$?([A-Za-z]{1,3}):\$?([A-Za-z]{1,3})$/.exec(ref.trim())

  if (columns) {
    const [left, right] = [columnIndex(columns[1]), columnIndex(columns[2])].sort((x, y) => x - y)

    return { startRow: 0, startColumn: left, endRow: MAX_ROWS - 1, endColumn: right }
  }

  const rows = /^\$?(\d{1,7}):\$?(\d{1,7})$/.exec(ref.trim())

  if (rows) {
    const [top, bottom] = [Number(rows[1]) - 1, Number(rows[2]) - 1].sort((x, y) => x - y)

    return top >= 0 ? { startRow: top, startColumn: 0, endRow: bottom, endColumn: MAX_COLUMNS - 1 } : null
  }

  return null
}

/** Space-separated ranges, as `sqref` lists them. */
export const parseRanges = (refs: string): CellRange[] => refs.split(/\s+/).flatMap((ref) => (ref ? (parseRange(ref) ?? []) : []))

export function rangeName(range: CellRange): string {
  const whole = range.startRow === 0 && range.endRow >= MAX_ROWS - 1

  if (whole) {
    return `${columnName(range.startColumn)}:${columnName(range.endColumn)}`
  }

  const start = cellName(range.startRow, range.startColumn)
  const end = cellName(range.endRow, range.endColumn)

  return start === end ? start : `${start}:${end}`
}

/** A sheet name as a formula writes it: quoted when it is not a plain word, with quotes doubled. */
export function quoteSheet(name: string): string {
  return /^[A-Za-z_][\w.]*$/.test(name) && !parseCell(name) ? name : `'${name.replace(/'/g, "''")}'`
}

/** "'My sheet'!A1:B2" as its sheet and reference. */
export function splitSheet(ref: string): { sheet?: string; ref: string } {
  const quoted = /^'((?:[^']|'')+)'!(.+)$/.exec(ref)

  if (quoted) {
    return { sheet: quoted[1].replace(/''/g, "'"), ref: quoted[2] }
  }

  const plain = /^([^!'[\]]+)!(.+)$/.exec(ref)

  return plain ? { sheet: plain[1], ref: plain[2] } : { ref }
}
