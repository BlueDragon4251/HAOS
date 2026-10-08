import type { CsvLayout } from '../../../../shared/office/csv.ts'
import { csvFromWorkbook, fieldFromCell, workbookFromCsv } from '../../../../shared/office/sheet-csv.ts'
import { cellsOf, newWorkbook, type WorkbookSnapshot } from '../../../../shared/office/workbook.ts'
import { decodeText, encodeText, escapeHtml, printPage, unitId } from '../print.ts'
import type { OfficeAdapter } from '../types.ts'

/*
 * Herald Sheets' files: CSV for now (Excel workbooks come with the format converters), and the
 * print view of the sheet in front.
 */

/** The sheet the window has in front, kept on the snapshot it hands over for saving and printing. */
export const activeSheetOf = (workbook: WorkbookSnapshot): string | undefined => (typeof workbook.activeSheetId === 'string' ? workbook.activeSheetId : undefined)

const CSS = `
@page { size: A4; margin: 0.5in; }
body { font: 9pt Arial, Helvetica, sans-serif; color: #000; margin: 0; }
h1 { font-size: 11pt; margin: 0 0 6pt; }
table { border-collapse: collapse; }
td { border: 0.5pt solid #c8ccd4; padding: 2pt 5pt; white-space: nowrap; vertical-align: bottom; }
td.n { text-align: right; }
`

export function printHtml(workbook: WorkbookSnapshot, title: string): { html: string; landscape: boolean } {
  const sheet = workbook.sheets[activeSheetOf(workbook) ?? ''] ?? workbook.sheets[workbook.sheetOrder[0]]
  const cells = sheet ? [...cellsOf(sheet)].filter(({ cell }) => fieldFromCell(cell) !== '') : []
  const rows = cells.length ? Math.max(...cells.map((entry) => entry.row)) + 1 : 0
  const columns = cells.length ? Math.max(...cells.map((entry) => entry.column)) + 1 : 0
  const body: string[] = []

  for (let row = 0; row < rows; row++) {
    const line: string[] = []

    for (let column = 0; column < columns; column++) {
      const cell = sheet.cellData[row]?.[column]
      const text = fieldFromCell(cell)
      line.push(`<td${typeof cell?.v === 'number' ? ' class="n"' : ''}>${escapeHtml(text)}</td>`)
    }

    body.push(`<tr>${line.join('')}</tr>`)
  }

  return { html: printPage(title, CSS, `<h1>${escapeHtml(sheet?.name ?? title)}</h1><table>${body.join('')}</table>`), landscape: columns > 8 }
}

export const sheetsAdapter: OfficeAdapter<WorkbookSnapshot> = {
  app: 'sheets',
  defaultFormat: '.csv',
  blank: (name) => newWorkbook(unitId('book'), name),
  read: async (bytes, _extension, name) => {
    const { text, notes } = decodeText(bytes)
    const { workbook, layout } = workbookFromCsv(text, { id: unitId('book'), name })

    return { model: workbook, notes, layout }
  },
  write: async (model, _extension, layout) => {
    const { text, losses } = csvFromWorkbook(model, { sheetId: activeSheetOf(model), layout: (layout ?? {}) as Partial<CsvLayout> })

    return { bytes: encodeText(text), losses }
  },
  print: async (model, name) => printHtml(model, name)
}
