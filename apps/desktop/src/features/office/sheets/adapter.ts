import { numfmt } from '@univerjs/core'
import { type CsvLayout, decodeCsv, encodeCsv } from '../../../../shared/office/csv.ts'
import { csvFromWorkbook, type NumberFormatter, workbookFromCsv } from '../../../../shared/office/sheet-csv.ts'
import { newWorkbook, type WorkbookSnapshot } from '../../../../shared/office/workbook.ts'
import { unitId } from '../print.ts'
import type { OfficeAdapter } from '../types.ts'
import { activeSheetOf, printHtml as printSheet } from './print.ts'
import { readXlsx, writeXlsx } from './xlsx.ts'

/*
 * Herald Sheets' files: Excel workbooks (.xlsx, and macro-enabled .xlsm opened without their
 * macros) and CSV, and the print view of the sheet in front.
 */

export { activeSheetOf }

/** Numbers as the sheet shows them, by Univer's own formatter (dates counted from 1904 in a workbook that does). */
export function formatterFor(workbook: WorkbookSnapshot): NumberFormatter {
  const shift = workbook.dateSystem === 'date1904' ? 1462 : 0

  return (value, pattern) => numfmt.format(pattern, shift && numfmt.isDateFormat(pattern) ? value + shift : value, { locale: 'en-US' })
}

export const printHtml = (workbook: WorkbookSnapshot, title: string) => printSheet(workbook, title, formatterFor(workbook))

const cannot = (extension: string, doing: string) => new Error(extension === '.ods' ? `Herald Sheets cannot ${doing} OpenDocument spreadsheets yet: LibreOffice can save this one as .xlsx first.` : `Herald Sheets cannot ${doing} ${extension || 'these'} files`)

export const sheetsAdapter: OfficeAdapter<WorkbookSnapshot> = {
  app: 'sheets',
  defaultFormat: '.xlsx',
  blank: (name) => newWorkbook(unitId('book'), name),
  read: async (bytes, extension, name) => {
    if (extension === '.csv') {
      const { text, encoding, notes } = decodeCsv(bytes)
      const { workbook, layout } = workbookFromCsv(text, { id: unitId('book'), name })

      return { model: workbook, notes, layout: { ...layout, encoding } }
    }

    if (extension === '.xlsx' || extension === '.xlsm') {
      const { workbook, notes } = await readXlsx(bytes, { id: unitId('book'), name, extension })

      return { model: workbook, notes }
    }

    throw cannot(extension, 'open')
  },
  write: async (model, extension, layout) => {
    if (extension === '.csv') {
      const csvLayout = (layout ?? {}) as Partial<CsvLayout>
      const { text, losses } = csvFromWorkbook(model, { sheetId: activeSheetOf(model), layout: csvLayout, format: formatterFor(model) })

      return { bytes: encodeCsv(text, csvLayout.encoding), losses }
    }

    if (extension === '.xlsx') {
      return writeXlsx(model)
    }

    throw cannot(extension, 'save')
  },
  print: async (model, name) => printHtml(model, name)
}
