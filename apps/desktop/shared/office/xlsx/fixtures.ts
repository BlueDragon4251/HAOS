import ExcelJS from 'exceljs'
import JSZip from 'jszip'
import type { WorkbookSnapshot } from '../workbook.ts'
import { readResource, RESOURCES } from './rules.ts'

/*
 * Workbooks for the converter tests, made here rather than taken from anywhere: one built with
 * ExcelJS with every feature Herald maps, and small packages written part by part, as other apps
 * write them (shared strings, custom number formats, theme colours, shared formulas).
 */

/** A workbook with every mapped feature, built with ExcelJS and given what ExcelJS cannot write (a filter condition). */
export async function featureWorkbook(): Promise<Uint8Array> {
  const book = new ExcelJS.Workbook()
  book.creator = 'Fixture'
  book.title = 'Features'
  const data = book.addWorksheet('Data', { properties: { tabColor: { argb: 'FF00B050' } }, views: [{ state: 'frozen', xSplit: 1, ySplit: 1, topLeftCell: 'B2', zoomScale: 125 }] })
  const other = book.addWorksheet('Other Sheet')
  book.addWorksheet('Hidden', { state: 'hidden' })
  book.addWorksheet('Secret', { state: 'veryHidden' })

  data.columns = [{ width: 20 }, { width: 12 }, { width: 9.140625, hidden: true }, { width: 30 }]
  data.getRow(1).values = ['Item', 'Cost', 'Hidden', 'Notes']
  data.getRow(1).font = { name: 'Arial', size: 14, bold: true, color: { argb: 'FFFFFFFF' } }
  data.getRow(1).fill = { type: 'pattern', pattern: 'solid', fgColor: { theme: 4, tint: 0.4 } as unknown as ExcelJS.Color }
  data.getRow(1).height = 30
  data.getRow(5).hidden = true

  data.getCell('A2').value = 'Rent'
  data.getCell('B2').value = 1200.5
  data.getCell('B2').numFmt = '#,##0.00'
  data.getCell('A3').value = '007'
  data.getCell('B3').value = true
  data.getCell('A4').value = new Date(Date.UTC(2026, 9, 8, 12, 30))
  data.getCell('A4').numFmt = 'yyyy-mm-dd hh:mm'
  data.getCell('B4').value = { error: '#DIV/0!' } as ExcelJS.CellErrorValue
  data.getCell('A6').value = { formula: 'B2*2', result: 2401 }
  data.getCell('B6').value = { formula: 'SUM(B2:B4)', result: 1200.5 }
  data.getCell('C6').value = { formula: 'XLOOKUP(A2,A2:A3,B2:B3)', result: 1200.5 }
  data.getCell('A7').value = { formula: 'B7+1', result: 2402, shareType: 'shared', ref: 'A7:A9' } as unknown as ExcelJS.CellValue
  data.getCell('A8').value = { sharedFormula: 'A7', result: 3 } as ExcelJS.CellSharedFormulaValue
  data.getCell('A9').value = { sharedFormula: 'A7', result: 3 } as ExcelJS.CellSharedFormulaValue
  data.getCell('B7').value = { formula: 'B2:B3*2', result: 2401, shareType: 'array', ref: 'B7:B8' } as unknown as ExcelJS.CellValue
  data.getCell('B8').value = 0
  data.getCell('D2').value = { richText: [{ text: 'Bold', font: { bold: true } }, { text: ' and ' }, { text: 'red', font: { color: { argb: 'FFFF0000' }, italic: true } }] }
  data.getCell('D3').value = { text: 'Example', hyperlink: 'https://example.com/a?b=1&c=2', tooltip: 'Opens the site' }
  data.getCell('D4').value = 'Wrapped text that runs long'
  data.getCell('D4').alignment = { wrapText: true, vertical: 'top', horizontal: 'center' }
  data.getCell('D5').value = 'Indented'
  data.getCell('D5').alignment = { indent: 2 }
  data.getCell('D6').value = 'Turned'
  data.getCell('D6').alignment = { textRotation: 45 }
  data.getCell('D7').value = 'Down'
  data.getCell('D7').alignment = { textRotation: -90 }
  data.getCell('D8').value = 'Stacked'
  data.getCell('D8').alignment = { textRotation: 'vertical' }
  data.getCell('E2').value = 'Fonts'
  data.getCell('E2').font = { name: 'Georgia', size: 9, underline: 'double', strike: true, color: { theme: 5 } as unknown as ExcelJS.Color }
  data.getCell('E3').value = 'Pattern'
  data.getCell('E3').fill = { type: 'pattern', pattern: 'darkGray', fgColor: { argb: 'FF000000' }, bgColor: { argb: 'FFFFFFFF' } }
  data.getCell('E4').value = 'Borders'
  data.getCell('E4').border = { top: { style: 'thin', color: { argb: 'FFFF0000' } }, left: { style: 'dashed' }, bottom: { style: 'double', color: { argb: 'FF0000FF' } }, right: { style: 'thick' } }
  data.getCell('E5').value = 'Diagonal'
  data.getCell('E5').border = { diagonal: { up: true, down: false, style: 'thin', color: { argb: 'FF00FF00' } } }
  data.getCell('E6').value = 0.25
  data.getCell('E6').numFmt = '0.0%'
  data.getCell('E7').value = 'Merged'
  data.mergeCells('E7:F8')
  data.getCell('F2').value = 'Link inside'
  data.getCell('G2').value = 'Super'
  data.getCell('G2').font = { vertAlign: 'superscript' }
  data.getCell('G3').value = 'Shrink'
  data.getCell('G3').alignment = { shrinkToFit: true }

  const validations = (data as unknown as { dataValidations: { add: (address: string, rule: ExcelJS.DataValidation) => void } }).dataValidations
  validations.add('H2', { type: 'list', allowBlank: true, formulae: ['"Yes,No,Maybe"'], showErrorMessage: true, errorStyle: 'warning', error: 'Pick one' })
  validations.add('H3', { type: 'whole', operator: 'between', formulae: [1, 10], showInputMessage: true, prompt: 'One to ten', promptTitle: 'Range' })
  validations.add('H4', { type: 'list', formulae: ["'Other Sheet'!$A$1:$A$3"] })

  data.addConditionalFormatting({
    ref: 'B2:B9',
    rules: [
      { type: 'cellIs', operator: 'greaterThan', formulae: [1000], priority: 1, style: { fill: { type: 'pattern', pattern: 'solid', bgColor: { argb: 'FFFFC7CE' } }, font: { color: { argb: 'FF9C0006' }, bold: true } } },
      { type: 'expression', formulae: ['MOD(ROW(),2)=0'], priority: 2, style: { fill: { type: 'pattern', pattern: 'solid', bgColor: { argb: 'FFEEEEEE' } } } }
    ]
  })
  data.addConditionalFormatting({ ref: 'A2:A9', rules: [{ type: 'containsText', operator: 'containsText', text: 'Ren', priority: 3, style: { font: { italic: true } } } as ExcelJS.ConditionalFormattingRule] })
  data.addConditionalFormatting({ ref: 'C2:C9', rules: [{ type: 'dataBar', priority: 4, cfvo: [{ type: 'min' }, { type: 'max' }], color: { argb: 'FF638EC6' }, gradient: true } as ExcelJS.ConditionalFormattingRule] })
  data.addConditionalFormatting({ ref: 'E2:E9', rules: [{ type: 'colorScale', priority: 5, cfvo: [{ type: 'min' }, { type: 'percentile', value: 50 }, { type: 'max' }], color: [{ argb: 'FFF8696B' }, { argb: 'FFFFEB84' }, { argb: 'FF63BE7B' }] }] })
  data.addConditionalFormatting({ ref: 'F2:F9', rules: [{ type: 'iconSet', priority: 6, iconSet: '3Arrows', cfvo: [{ type: 'percent', value: 0 }, { type: 'percent', value: 33 }, { type: 'percent', value: 67 }] }] })
  data.addConditionalFormatting({ ref: 'G2:G9', rules: [{ type: 'top10', priority: 7, rank: 3, percent: false, bottom: true, style: { font: { bold: true } } }] })

  data.autoFilter = 'A1:D9'
  book.definedNames.add("'Other Sheet'!$A$1:$A$3", 'Choices')

  other.getCell('A1').value = 'One'
  other.getCell('A2').value = 'Two'
  other.getCell('A3').value = 'Three'
  other.getCell('B1').value = { formula: "Data!B2+'Other Sheet'!C1", result: 1200.5 }
  other.pageSetup = { orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0, paperSize: 9 }
  other.headerFooter = { oddFooter: '&LConfidential&RPage &P' }

  const bytes = new Uint8Array((await book.xlsx.writeBuffer()) as ArrayBuffer)

  // ExcelJS writes a filter's range only, and internal links badly: put in what Excel would write.
  return patchParts(bytes, {
    'xl/worksheets/sheet1.xml': (xml) =>
      xml
        .replace(/<autoFilter ref="A1:D9"\/>/, '<autoFilter ref="A1:D9"><filterColumn colId="1"><customFilters><customFilter operator="greaterThan" val="100"/></customFilters></filterColumn></autoFilter>')
        .replace(/(<hyperlinks>)/, '$1<hyperlink ref="F2" location="\'Other Sheet\'!B1" display="Link inside"/>')
  })
}

type Json = Record<string, unknown>

/**
 * What a workbook says, for comparing two: styles written into the cells, and without what each
 * reading makes up (ids of rules and links) or what Univer adds for its own view (scrolling, headers).
 */
export function normalized(workbook: WorkbookSnapshot): Json {
  const style = (id: unknown) => (typeof id === 'string' ? workbook.styles[id] : id)
  const strip = (value: unknown): unknown => JSON.parse(JSON.stringify(value ?? null), (key, entry) => (key === 'rangeId' || key === 'cfId' || key === 'uid' || key === 'unitId' || key === 'sheetId' ? undefined : entry))
  const sheets = workbook.sheetOrder.map((id) => {
    const { cellData, rowData, columnData, scrollTop: _top, scrollLeft: _left, rowHeader: _rows, columnHeader: _columns, ...rest } = workbook.sheets[id]
    const cells = Object.fromEntries(Object.entries(cellData ?? {}).map(([row, columns]) => [row, Object.fromEntries(Object.entries(columns).map(([column, cell]) => [column, strip({ ...cell, s: style(cell.s) })]))]))
    const lines = (data: unknown) => Object.fromEntries(Object.entries((data ?? {}) as Record<string, Json>).map(([index, meta]) => [index, { ...meta, s: style(meta.s) }]))

    return { ...rest, cells, rows: lines(rowData), columns: lines(columnData) }
  })
  const names = Object.values(readResource<Record<string, Json>>(workbook.resources, RESOURCES.definedNames) ?? {}).map(({ id: _id, ...name }) => name)
  // A saved file always has a creation date: the original's, or the day it was first saved.
  const { created: _created, ...properties } = ((workbook.custom as { herald?: { properties?: Json } } | undefined)?.herald?.properties ?? {}) as Json
  const filters = readResource<Record<string, { cachedFilteredOut?: number[] }>>(workbook.resources, RESOURCES.filter)

  return {
    sheets,
    activeSheetId: workbook.activeSheetId,
    dateSystem: workbook.dateSystem,
    defaultStyle: workbook.defaultStyle,
    properties,
    names,
    filters: strip(filters),
    validations: strip(readResource(workbook.resources, RESOURCES.validation)),
    conditional: strip(readResource(workbook.resources, RESOURCES.conditional))
  }
}

/** Change parts of a package: each function gets a part's XML and returns the new one. */
export async function patchParts(bytes: Uint8Array, changes: Record<string, (xml: string) => string>): Promise<Uint8Array> {
  const zip = await JSZip.loadAsync(bytes)

  for (const [path, change] of Object.entries(changes)) {
    const xml = (await zip.file(path)?.async('string')) ?? ''
    zip.file(path, change(xml))
  }

  return zip.generateAsync({ type: 'uint8array' })
}

const CONTENT_TYPES = (extra = '') =>
  `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/><Override PartName="/xl/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>${extra}</Types>`

const MAIN = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

/** A theme whose accent 1 is plain to check: dark green; accent 2 purple. */
const THEME = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Test"><a:themeElements><a:clrScheme name="Test"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1F3864"/></a:dk2><a:lt2><a:srgbClr val="EEECE1"/></a:lt2><a:accent1><a:srgbClr val="006400"/></a:accent1><a:accent2><a:srgbClr val="7030A0"/></a:accent2><a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4><a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme><a:fontScheme name="Test"><a:majorFont><a:latin typeface="Cambria"/></a:majorFont><a:minorFont><a:latin typeface="Verdana"/></a:minorFont></a:fontScheme><a:fmtScheme name="Test"/></a:themeElements></a:theme>`

/**
 * A package written part by part, as another app writes it: shared strings, styles with custom
 * number formats, theme and indexed colours, a shared formula, and extra parts when asked.
 */
export async function handmadePackage(options: { extraParts?: Record<string, string>; sheetTail?: string; workbookExtra?: string; sheetRels?: string; extraContentTypes?: string } = {}): Promise<Uint8Array> {
  const zip = new JSZip()
  zip.file('[Content_Types].xml', CONTENT_TYPES(options.extraContentTypes))
  zip.file('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
  zip.file(
    'xl/_rels/workbook.xml.rels',
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/></Relationships>'
  )
  zip.file('xl/workbook.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook ${MAIN}><workbookPr date1904="1"/><bookViews><workbookView activeTab="0"/></bookViews><sheets><sheet name="Hand Made" sheetId="1" r:id="rId1"/></sheets>${options.workbookExtra ?? ''}</workbook>`)
  zip.file('xl/sharedStrings.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst ${MAIN} count="3" uniqueCount="3"><si><t>Amount</t></si><si><t xml:space="preserve"> padded </t></si><si><r><rPr><b/><sz val="12"/><color theme="4"/><rFont val="Verdana"/></rPr><t>Rich</t></r><r><t> run</t></r></si></sst>`)
  zip.file(
    'xl/styles.xml',
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet ${MAIN}><numFmts count="2"><numFmt numFmtId="164" formatCode="&quot;$&quot;#,##0.00;[Red]\\-&quot;$&quot;#,##0.00"/><numFmt numFmtId="165" formatCode="dd/mm/yyyy"/></numFmts><fonts count="3"><font><sz val="10"/><color theme="1"/><name val="Verdana"/><family val="2"/><scheme val="minor"/></font><font><b/><sz val="10"/><color theme="4" tint="-0.249977111117893"/><name val="Verdana"/></font><font><i/><sz val="10"/><color indexed="10"/><name val="Verdana"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor theme="5" tint="0.79998168889431442"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="medium"><color indexed="12"/></left><right/><top/><bottom style="hair"><color auto="1"/></bottom><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="164" fontId="1" fillId="2" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"/><xf numFmtId="165" fontId="2" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/><xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`
  )
  zip.file('xl/theme/theme1.xml', THEME)
  zip.file(
    'xl/worksheets/sheet1.xml',
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet ${MAIN}><dimension ref="A1:C6"/><sheetViews><sheetView workbookViewId="0" showGridLines="0"/></sheetViews><sheetFormatPr baseColWidth="10" defaultRowHeight="13"/><cols><col min="2" max="2" width="15.5" customWidth="1"/></cols><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row><row r="2"><c r="A2"><v>10</v></c><c r="B2" s="1"><v>-1234.5</v></c><c r="C2" s="2"><v>45000</v></c></row><row r="3"><c r="A3"><v>20</v></c><c r="B3"><f t="shared" ref="B3:B5" si="0">A3*2</f><v>40</v></c><c r="C3" s="3"><v>0.125</v></c></row><row r="4"><c r="A4"><v>30</v></c><c r="B4"><f t="shared" si="0"/><v>60</v></c><c r="C4" s="4"><v>1</v></c></row><row r="5"><c r="A5"><v>40</v></c><c r="B5"><f t="shared" si="0"/><v>80</v></c><c r="C5" t="b"><v>1</v></c></row><row r="6" ht="24" customHeight="1"><c r="A6" t="e"><v>#N/A</v></c><c r="B6" t="str"><f>"x"&amp;A2</f><v>x10</v></c><c r="C6" t="inlineStr"><is><t>inline</t></is></c></row></sheetData>${options.sheetTail ?? ''}</worksheet>`
  )

  if (options.sheetRels) {
    zip.file('xl/worksheets/_rels/sheet1.xml.rels', options.sheetRels)
  }

  for (const [path, content] of Object.entries(options.extraParts ?? {})) {
    zip.file(path, content)
  }

  return zip.generateAsync({ type: 'uint8array' })
}
