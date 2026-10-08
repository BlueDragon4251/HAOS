import type { XlsxPackage } from './package.ts'

/*
 * What an .xlsx file holds that Herald Sheets drops, found by looking at the package's parts
 * rather than at what ExcelJS happened to read: charts, pivot tables, macros, pictures and shapes,
 * notes, links to other workbooks, slicers, sparklines, protection, print settings and the rest.
 * Each note says what happens to the thing, for the fidelity report before the first save.
 */

/** "one chart", "3 charts". */
export function counted(n: number, singular: string, plural = `${singular}s`): string {
  return n === 1 ? `one ${singular}` : `${n.toLocaleString('en-US')} ${plural}`
}

const capital = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1)

/** How many times `pattern` occurs in `text`. */
const occurrences = (text: string, pattern: RegExp): number => text.match(pattern)?.length ?? 0

export interface PackageReport {
  notes: string[]
  /** The file has macros (a VBA project), which no saved copy keeps. */
  macros: boolean
}

export async function inspectPackage(pkg: XlsxPackage, extension = '.xlsx'): Promise<PackageReport> {
  const notes: string[] = []
  const files = pkg.files
  const count = (pattern: RegExp) => files.filter((file) => pattern.test(file)).length
  const readAll = async (pattern: RegExp) => (await Promise.all(files.filter((file) => pattern.test(file)).map((file) => pkg.read(file)))).join('\n')
  const macros = files.some((file) => /(^|\/)vbaProject\.bin$/i.test(file)) || extension === '.xlsm'

  if (macros) {
    notes.push('Macros (VBA) are not kept: Herald Sheets does not run them, and a copy it saves has none.')
  }

  const charts = count(/^xl\/charts\/chart(?:Ex)?\d*\.xml$/i)
  const chartSheets = pkg.sheets.filter((sheet) => sheet.kind === 'chartsheet').length

  if (charts) {
    notes.push(`${capital(counted(charts, 'chart'))} ${charts === 1 ? 'is' : 'are'} not kept; the data ${charts === 1 ? 'it shows stays' : 'they show stays'}.`)
  }

  if (chartSheets) {
    notes.push(`${capital(counted(chartSheets, 'chart sheet'))} (a sheet holding only a chart) ${chartSheets === 1 ? 'is' : 'are'} left out.`)
  }

  const otherSheets = pkg.sheets.filter((sheet) => sheet.kind === 'dialogsheet' || sheet.kind === 'macrosheet' || sheet.kind === 'other').length

  if (otherSheets) {
    notes.push(`${capital(counted(otherSheets, 'dialog or Excel 4.0 macro sheet'))} ${otherSheets === 1 ? 'is' : 'are'} left out.`)
  }

  const pivots = count(/^xl\/pivotTables\/pivotTable\d*\.xml$/i)

  if (pivots) {
    notes.push(`${capital(counted(pivots, 'pivot table'))}: ${pivots === 1 ? 'its' : 'their'} cells stay as plain values, without the pivot table that made them.`)
  }

  const drawings = await readAll(/^xl\/drawings\/drawing\d*\.xml$/i)
  const pictures = occurrences(drawings, /<xdr:pic>/g) + occurrences(drawings, /<xdr:pic\s/g)
  const shapes = occurrences(drawings, /<xdr:sp[\s>]/g) + occurrences(drawings, /<xdr:cxnSp[\s>]/g)

  if (pictures) {
    notes.push(`${capital(counted(pictures, 'picture'))} ${pictures === 1 ? 'is' : 'are'} not shown or kept.`)
  }

  if (shapes) {
    notes.push(`${capital(counted(shapes, 'shape or text box', 'shapes and text boxes'))} ${shapes === 1 ? 'is' : 'are'} not shown or kept.`)
  }

  const comments = occurrences(await readAll(/^xl\/comments\d*\.xml$/i), /<comment\s/g)
  const threads = occurrences(await readAll(/^xl\/threadedComments\/threadedComment\d*\.xml$/i), /<threadedComment\s(?![^>]*parentId=)/g)

  if (threads) {
    notes.push(`${capital(counted(threads, 'comment thread'))} ${threads === 1 ? 'is' : 'are'} not shown or kept.`)
  } else if (comments) {
    notes.push(`${capital(counted(comments, 'note'))} on cells ${comments === 1 ? 'is' : 'are'} not shown or kept.`)
  }

  const externals = count(/^xl\/externalLinks\/externalLink\d*\.xml$/i)

  if (externals) {
    notes.push(`Links to ${counted(externals, 'other workbook')} are not kept; formulas that use them keep their last values until they are worked out again.`)
  }

  const tables = count(/^xl\/tables\/table\d*\.xml$/i)

  if (tables) {
    notes.push(`${capital(counted(tables, 'table'))} ${tables === 1 ? 'becomes a plain range' : 'become plain ranges'}: data and formatting stay, the table and formulas that name its columns do not.`)
  }

  if (count(/^xl\/(slicers|slicerCaches|timelines|timelineCaches)\//i)) {
    notes.push('Slicers and timelines are not kept.')
  }

  const sheetParts = pkg.sheets.map((sheet) => `${sheet.head}${sheet.tail}`).join('\n')

  if (/<(?:\w+:)?sparklineGroup[\s>]/.test(sheetParts)) {
    notes.push('Sparklines (small charts in cells) are not kept.')
  }

  if (/<(?:\w+:)?(sheetProtection|protectedRange)[\s>]/.test(sheetParts) || /<(?:\w+:)?(workbookProtection|fileSharing)[\s>]/.test(pkg.workbookXml)) {
    notes.push('Protection (locked sheets, structure or a password to open for editing) is not kept: a saved copy is unprotected.')
  }

  if (/<(?:\w+:)?(rowBreaks|colBreaks)[\s>]/.test(sheetParts) || pkg.definedNames.some((name) => /^_xlnm\.(Print_Area|Print_Titles)$/i.test(name.name))) {
    notes.push('Print areas, print titles and page breaks are not kept; page size, orientation, margins, scaling and headers stay.')
  }

  if (/outlineLevel(?:Row|Col)="[1-9]/.test(sheetParts) || /<(?:\w+:)?col\s[^>]*outlineLevel="[1-9]/.test(sheetParts)) {
    notes.push('Grouped rows and columns are shown ungrouped; rows and columns that were collapsed stay hidden.')
  }

  if (/<(?:\w+:)?picture\s/.test(sheetParts)) {
    notes.push('Sheet background pictures are not kept.')
  }

  if (count(/^xl\/(ctrlProps|activeX)\//i) || /<(?:\w+:)?controls[\s>]/.test(sheetParts)) {
    notes.push('Form controls (buttons, check boxes, lists) are not kept.')
  }

  if (count(/^xl\/embeddings\//i) || /<(?:\w+:)?oleObjects[\s>]/.test(sheetParts)) {
    notes.push('Embedded objects (other documents inside the workbook) are not kept.')
  }

  if (count(/^xl\/(connections\.xml|queryTables\/)/i) || count(/^xl\/model\//i)) {
    notes.push('Data connections, queries and the data model are not kept; their last results stay as values.')
  }

  if (count(/^xl\/richData\//i)) {
    notes.push('Pictures in cells and linked data types (such as stocks) are shown as plain values.')
  }

  if (/fDynamic="(1|true)"/.test((await pkg.read('xl/metadata.xml')) ?? '')) {
    notes.push('Formulas that spill (dynamic arrays) are saved as fixed-size array formulas.')
  }

  if (/<(?:\w+:)?customSheetViews[\s>]/.test(sheetParts)) {
    notes.push('Custom views are not kept.')
  }

  if (/<(?:\w+:)?scenarios[\s>]/.test(sheetParts)) {
    notes.push('What-if scenarios are not kept.')
  }

  if (count(/^xl\/revisions\//i)) {
    notes.push('The shared workbook’s change history is not kept.')
  }

  if (count(/^_xmlsignatures\//i)) {
    notes.push('The digital signature does not survive saving: a saved copy is unsigned.')
  }

  if (count(/^docProps\/custom\.xml$/i)) {
    notes.push('Custom document properties are not kept.')
  }

  return { notes, macros }
}
