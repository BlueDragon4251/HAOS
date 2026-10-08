import { describe, expect, it } from 'vitest'
import { counted } from './fidelity.ts'
import { featureWorkbook, handmadePackage, patchParts } from './fixtures.ts'
import { workbookFromXlsx } from './read.ts'

const DRAWING = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><xdr:twoCellAnchor><xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="2" name="Chart 1"/></xdr:nvGraphicFramePr></xdr:graphicFrame></xdr:twoCellAnchor><xdr:oneCellAnchor><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="3" name="Picture 1"/></xdr:nvPicPr></xdr:pic></xdr:oneCellAnchor><xdr:oneCellAnchor><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="4" name="Picture 2"/></xdr:nvPicPr></xdr:pic></xdr:oneCellAnchor><xdr:twoCellAnchor><xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="5" name="TextBox 1"/></xdr:nvSpPr></xdr:sp></xdr:twoCellAnchor></xdr:wsDr>`
const COMMENTS = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><authors><author>A</author></authors><commentList><comment ref="A1" authorId="0"><text><t>one</t></text></comment><comment ref="B2" authorId="0"><text><t>two</t></text></comment></commentList></comments>'

async function notesOf(bytes: Uint8Array, extension = '.xlsx'): Promise<string[]> {
  return (await workbookFromXlsx(bytes, { id: 'f', name: 'Fidelity', extension })).notes
}

describe('fidelity report', () => {
  it('finds charts, pictures, shapes, notes, pivot tables, macros and the rest in the package parts', async () => {
    const bytes = await handmadePackage({
      extraParts: {
        'xl/drawings/drawing1.xml': DRAWING,
        'xl/charts/chart1.xml': '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"/>',
        'xl/comments1.xml': COMMENTS,
        'xl/pivotTables/pivotTable1.xml': '<pivotTableDefinition/>',
        'xl/pivotCache/pivotCacheDefinition1.xml': '<pivotCacheDefinition/>',
        'xl/vbaProject.bin': 'binary',
        'xl/externalLinks/externalLink1.xml': '<externalLink/>',
        'xl/externalLinks/externalLink2.xml': '<externalLink/>',
        'xl/tables/table1.xml': '<table/>',
        'xl/slicers/slicer1.xml': '<slicers/>',
        'xl/embeddings/oleObject1.bin': 'binary',
        'xl/ctrlProps/ctrlProp1.xml': '<formControlPr/>',
        'xl/richData/rdrichvalue.xml': '<rvData/>',
        'xl/metadata.xml': '<metadata><dynamicArrayProperties fDynamic="1" fCollapsed="0"/></metadata>',
        'docProps/custom.xml': '<Properties/>',
        '_xmlsignatures/sig1.xml': '<Signature/>'
      },
      sheetTail: '<sheetProtection sheet="1" objects="1"/><rowBreaks count="1"><brk id="10" max="16383" man="1"/></rowBreaks><extLst><ext uri="{05C60535-1F16-4fd2-B633-F4F36F0B64E0}"><x14:sparklineGroups xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"><x14:sparklineGroup><x14:sparklines/></x14:sparklineGroup></x14:sparklineGroups></ext></extLst>',
      workbookExtra: '<definedNames><definedName name="_xlnm.Print_Area" localSheetId="0">\'Hand Made\'!$A$1:$C$6</definedName><definedName name="Rate">0.07</definedName></definedNames>'
    })
    // The table part is broken: ExcelJS fails on it, and the second reading leaves it out.
    const { workbook, notes } = await workbookFromXlsx(bytes, { id: 'f', name: 'Fidelity' })

    expect(workbook.sheets[workbook.sheetOrder[0]].cellData[1][0]).toEqual({ v: 10, t: 2 })
    expect(notes).toEqual([
      'Macros (VBA) are not kept: Herald Sheets does not run them, and a copy it saves has none.',
      'One chart is not kept; the data it shows stays.',
      'One pivot table: its cells stay as plain values, without the pivot table that made them.',
      '2 pictures are not shown or kept.',
      'One shape or text box is not shown or kept.',
      '2 notes on cells are not shown or kept.',
      'Links to 2 other workbooks are not kept; formulas that use them keep their last values until they are worked out again.',
      'One table becomes a plain range: data and formatting stay, the table and formulas that name its columns do not.',
      'Slicers and timelines are not kept.',
      'Sparklines (small charts in cells) are not kept.',
      'Protection (locked sheets, structure or a password to open for editing) is not kept: a saved copy is unprotected.',
      'Print areas, print titles and page breaks are not kept; page size, orientation, margins, scaling and headers stay.',
      'Form controls (buttons, check boxes, lists) are not kept.',
      'Embedded objects (other documents inside the workbook) are not kept.',
      'Pictures in cells and linked data types (such as stocks) are shown as plain values.',
      'Formulas that spill (dynamic arrays) are saved as fixed-size array formulas.',
      'The digital signature does not survive saving: a saved copy is unsigned.',
      'Custom document properties are not kept.'
    ])
  })

  it('names macros for a macro-enabled workbook, and leaves out chart sheets', async () => {
    const bytes = await patchParts(await handmadePackage({ extraParts: { 'xl/chartsheets/sheet2.xml': '<chartsheet/>' } }), {
      'xl/workbook.xml': (xml) => xml.replace('</sheets>', '<sheet name="Chart1" sheetId="2" r:id="rId9"/></sheets>'),
      'xl/_rels/workbook.xml.rels': (xml) => xml.replace('</Relationships>', '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chartsheet" Target="chartsheets/sheet2.xml"/></Relationships>')
    })
    const { workbook, notes } = await workbookFromXlsx(bytes, { id: 'f', name: 'F', extension: '.xlsm' })

    expect(notes).toEqual(['Macros (VBA) are not kept: Herald Sheets does not run them, and a copy it saves has none.', 'One chart sheet (a sheet holding only a chart) is left out.'])
    expect(workbook.sheetOrder).toHaveLength(1)
  })

  it('has nothing to say about a plain workbook', async () => {
    expect(await notesOf(await handmadePackage())).toEqual([])
    expect((await notesOf(await featureWorkbook())).filter((note) => !note.startsWith('Patterned'))).toEqual([])
  })

  it('counts in words for one', () => {
    expect([counted(1, 'chart'), counted(3, 'chart'), counted(1200, 'note'), counted(2, 'shape or text box', 'shapes and text boxes')]).toEqual(['one chart', '3 charts', '1,200 notes', '2 shapes and text boxes'])
  })
})
