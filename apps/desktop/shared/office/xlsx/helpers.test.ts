import { describe, expect, it } from 'vitest'
import { columnIndex, columnName, parseRange, parseRanges, quoteSheet, rangeName, splitSheet } from './address.ts'
import { argbOf, DEFAULT_PALETTE, indexedColors, resolveColor, themeColors, tinted } from './colors.ts'
import { formulaFromExcel, formulaToExcel, slideFormula } from './formula.ts'
import { columnPixels, columnWidth, defaultColumnPixels, pixelsToPoints, pointsToPixels } from './units.ts'
import { attributesOf, decodeXml, elementsOf, textOf } from './xml.ts'

describe('A1 references', () => {
  it('names and reads columns, cells and ranges', () => {
    expect([0, 25, 26, 701, 702, 16383].map(columnName)).toEqual(['A', 'Z', 'AA', 'ZZ', 'AAA', 'XFD'])
    expect(['A', 'AA', 'XFD'].map(columnIndex)).toEqual([0, 26, 16383])
    expect(parseRange('$B$2:A1')).toEqual({ startRow: 0, startColumn: 0, endRow: 1, endColumn: 1 })
    expect(parseRange('C:D')).toMatchObject({ startColumn: 2, endColumn: 3, startRow: 0, endRow: 1048575 })
    expect(parseRange('3:5')).toMatchObject({ startRow: 2, endRow: 4, startColumn: 0 })
    expect(parseRange('Sheet1')).toBeNull()
    expect(parseRanges('A1 C3:D4')).toHaveLength(2)
    expect(rangeName({ startRow: 0, startColumn: 2, endRow: 1048575, endColumn: 2 })).toBe('C:C')
    expect(rangeName({ startRow: 4, startColumn: 1, endRow: 4, endColumn: 1 })).toBe('B5')
  })

  it('quotes and splits sheet names', () => {
    expect(quoteSheet('Data')).toBe('Data')
    expect(quoteSheet("Bob's sheet")).toBe("'Bob''s sheet'")
    expect(quoteSheet('A1')).toBe("'A1'")
    expect(splitSheet("'Bob''s sheet'!$A$1")).toEqual({ sheet: "Bob's sheet", ref: '$A$1' })
    expect(splitSheet('Data!B2:C3')).toEqual({ sheet: 'Data', ref: 'B2:C3' })
  })
})

describe('formulas', () => {
  it('drops the prefixes of newer functions, but not inside text', () => {
    expect(formulaFromExcel('_xlfn.XLOOKUP(A1,_xlfn._xlws.FILTER(B:B,C:C>0),"_xlfn.kept")')).toBe('=XLOOKUP(A1,FILTER(B:B,C:C>0),"_xlfn.kept")')
    expect(formulaFromExcel('SUM(A1:A3)')).toBe('=SUM(A1:A3)')
  })

  it('prefixes newer functions for the file, and drops references to the workbook itself', () => {
    expect(formulaToExcel('=XLOOKUP(A1,filter(B:B,C:C>0),"xlookup(")+SUM(1)')).toBe('_xlfn.XLOOKUP(A1,_xlfn._xlws.filter(B:B,C:C>0),"xlookup(")+SUM(1)')
    expect(formulaToExcel('=STDEV.S(A1:A9)+[book]Sheet1!A1', 'book')).toBe('_xlfn.STDEV.S(A1:A9)+Sheet1!A1')
  })

  it('names the parameters of LET and LAMBDA with _xlpm. for the file, and reads them back without it', () => {
    const let_ = '=LET(rate,0.07,total,SUM(B2:B9),total*(1+rate))'
    const lambda = '=LAMBDA(a, b, a+b+"a")(1,2)+MAP(A1:A3,LAMBDA(x,x*2))'

    expect(formulaToExcel(let_)).toBe('_xlfn.LET(_xlpm.rate,0.07,_xlpm.total,SUM(B2:B9),_xlpm.total*(1+_xlpm.rate))')
    expect(formulaToExcel(lambda)).toBe('_xlfn.LAMBDA(_xlpm.a, _xlpm.b, _xlpm.a+_xlpm.b+"a")(1,2)+_xlfn.MAP(A1:A3,_xlfn.LAMBDA(_xlpm.x,_xlpm.x*2))')
    expect(formulaFromExcel(formulaToExcel(let_))).toBe(let_)
    expect(formulaFromExcel(formulaToExcel(lambda))).toBe(lambda)
    expect(formulaToExcel("=SUM('Let it be'!A1,[Let]x)")).toBe("SUM('Let it be'!A1,[Let]x)")
  })

  it('slides relative references, as a shared formula does', () => {
    const formula = 'A1+$B$1+C$2+$D3+SUM(A:A)+ROWS(1:2)+Sheet1!E5+\'My Sheet\'!F6+"A1"+LOG10(5)+1E5+Table1[Cost]'

    expect(slideFormula(formula, 2, 1)).toBe('B3+$B$1+D$2+$D5+SUM(B:B)+ROWS(3:4)+Sheet1!F7+\'My Sheet\'!G8+"A1"+LOG10(5)+1E5+Table1[Cost]')
    expect(slideFormula('A1*2', -1, 0)).toBe('#REF!*2')
    expect(slideFormula('Q1!A1', 0, 0)).toBe('Q1!A1')
  })
})

describe('colours', () => {
  it('works out tints as Excel does', () => {
    expect(tinted('4F81BD', 0.4)).toBe('95B3D7')
    expect(tinted('006400', -0.25)).toBe('004B00')
    expect(tinted('FFFFFF', -0.5)).toBe('808080')
  })

  it('reads a theme in index order, the palette, and colours of every kind', () => {
    const theme = themeColors('<a:clrScheme name="T"><a:dk1><a:sysClr val="windowText" lastClr="111111"/></a:dk1><a:lt1><a:srgbClr val="FEFEFE"/></a:lt1><a:accent1><a:srgbClr val="ABCDEF"/></a:accent1></a:clrScheme>')

    expect(theme.slice(0, 2)).toEqual(['FEFEFE', '111111'])
    expect(theme[4]).toBe('ABCDEF')
    expect(theme[5]).toBe('ED7D31')
    expect(indexedColors('<indexedColors><rgbColor rgb="FF123456"/></indexedColors>')[0]).toBe('123456')
    expect(resolveColor({ theme: 4 }, { theme, indexed: DEFAULT_PALETTE.indexed })).toBe('#abcdef')
    expect(resolveColor({ indexed: 10 }, DEFAULT_PALETTE)).toBe('#ff0000')
    expect(resolveColor({ argb: 'FF00B050' }, DEFAULT_PALETTE)).toBe('#00b050')
    expect(resolveColor(undefined, DEFAULT_PALETTE)).toBeNull()
    expect(['#abc', '#A1B2C3', 'rgb(255, 0, 10)', 'rgba(1,2,3,0.5)', 'tomato'].map(argbOf)).toEqual(['FFAABBCC', 'FFA1B2C3', 'FFFF000A', 'FF010203', null])
  })
})

describe('sizes', () => {
  it('turns column widths and row heights into pixels and back', () => {
    expect(columnPixels(9.140625)).toBe(64)
    expect(columnWidth(64)).toBe(9.140625)

    for (const pixels of [20, 64, 88, 100, 250]) {
      expect(columnPixels(columnWidth(pixels))).toBe(pixels)
    }

    expect(defaultColumnPixels(undefined, 8)).toBe(64)
    expect(defaultColumnPixels(undefined, 10)).toBe(80)
    expect(defaultColumnPixels(12.5)).toBe(columnPixels(12.5))
    expect(pointsToPixels(15)).toBe(20)
    expect(pixelsToPoints(20)).toBe(15)
  })
})

describe('xml', () => {
  it('reads attributes, elements with and without prefixes, and text', () => {
    expect(attributesOf('<c r="A1" t=\'s\' x:y="&amp;"')).toEqual({ r: 'A1', t: 's', 'x:y': '&' })
    expect(decodeXml('&lt;&#65;&#x42;&quot;')).toBe('<AB"')
    const xml = '<dataValidations><dataValidation sqref="A1"><formula1>"a,b"</formula1></dataValidation><x14:dataValidation><xm:sqref>B2</xm:sqref></x14:dataValidation></dataValidations>'

    expect(elementsOf(xml, 'dataValidation').map((entry) => entry.attributes.sqref ?? textOf(entry.inner, 'sqref'))).toEqual(['A1', 'B2'])
    expect(textOf(xml, 'formula1')).toBe('"a,b"')
  })
})
