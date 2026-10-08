import { columnIndex, columnName, MAX_COLUMNS, MAX_ROWS } from './address.ts'

/*
 * Formulas between Excel's file text and Univer's. A file writes functions newer than Excel 2007
 * with prefixes (`_xlfn.XLOOKUP`, `_xlfn._xlws.FILTER`) and leaves out the "="; Univer shows and
 * works out formulas without the prefixes, with the "=". The references of a shared formula are
 * slid from its first cell to each of the others, as Excel does.
 */

/** Functions a file names with `_xlfn.`: the ones Excel added after 2007. */
const NEWER = new Set(
  (
    'ACOT ACOTH AGGREGATE ARABIC ARRAYTOTEXT BASE BETA.DIST BETA.INV BINOM.DIST BINOM.DIST.RANGE BINOM.INV BITAND BITLSHIFT BITOR BITRSHIFT BITXOR BYCOL BYROW ' +
    'CEILING.MATH CEILING.PRECISE CHISQ.DIST CHISQ.DIST.RT CHISQ.INV CHISQ.INV.RT CHISQ.TEST CHOOSECOLS CHOOSEROWS COMBINA CONCAT CONFIDENCE.NORM CONFIDENCE.T COT COTH ' +
    'COVARIANCE.P COVARIANCE.S CSC CSCH DAYS DECIMAL DROP ERF.PRECISE ERFC.PRECISE EXPAND EXPON.DIST F.DIST F.DIST.RT F.INV F.INV.RT F.TEST FIELDVALUE FILTERXML ' +
    'FLOOR.MATH FLOOR.PRECISE FORECAST.ETS FORECAST.ETS.CONFINT FORECAST.ETS.SEASONALITY FORECAST.ETS.STAT FORECAST.LINEAR FORMULATEXT GAMMA GAMMA.DIST GAMMA.INV ' +
    'GAMMALN.PRECISE GAUSS GROUPBY HSTACK HYPGEOM.DIST IFNA IFS IMAGE IMCOSH IMCOT IMCSC IMCSCH IMSEC IMSECH IMSINH IMTAN ISFORMULA ISOMITTED ISOWEEKNUM LAMBDA LET ' +
    'LOGNORM.DIST LOGNORM.INV MAKEARRAY MAP MAXIFS MINIFS MODE.MULT MODE.SNGL MUNIT NEGBINOM.DIST NETWORKDAYS.INTL NORM.DIST NORM.INV NORM.S.DIST NORM.S.INV ' +
    'NUMBERVALUE PDURATION PERCENTILE.EXC PERCENTILE.INC PERCENTOF PERCENTRANK.EXC PERCENTRANK.INC PERMUTATIONA PHI PIVOTBY POISSON.DIST QUARTILE.EXC QUARTILE.INC ' +
    'RANDARRAY RANK.AVG RANK.EQ REDUCE REGEXEXTRACT REGEXREPLACE REGEXTEST RRI SCAN SEC SECH SEQUENCE SHEET SHEETS SKEW.P SORTBY STDEV.P STDEV.S STOCKHISTORY SWITCH ' +
    'T.DIST T.DIST.2T T.DIST.RT T.INV T.INV.2T T.TEST TAKE TEXTAFTER TEXTBEFORE TEXTJOIN TEXTSPLIT TOCOL TOROW TRIMRANGE UNICHAR UNICODE UNIQUE VALUETOTEXT VAR.P ' +
    'VAR.S VSTACK WEBSERVICE WEIBULL.DIST WORKDAY.INTL WRAPCOLS WRAPROWS XLOOKUP XMATCH XOR Z.TEST'
  ).split(' ')
)

/** Newer still: these carry `_xlfn._xlws.`. */
const WORKSHEET_ONLY = new Set(['FILTER', 'SORT'])

/** Run `change` on the parts of a formula outside strings, quoted sheet names and structured references. */
function outsideLiterals(formula: string, change: (part: string) => string): string {
  let out = ''
  let plain = ''
  let i = 0

  while (i < formula.length) {
    const char = formula[i]

    if (char === '"' || char === "'" || char === '[') {
      out += change(plain)
      plain = ''
      let end = i + 1

      if (char === '[') {
        for (let depth = 1; end < formula.length && depth > 0; end++) {
          depth += formula[end] === '[' ? 1 : formula[end] === ']' ? -1 : 0
        }
      } else {
        while (end < formula.length) {
          if (formula[end] === char && formula[end + 1] === char) {
            end += 2
          } else if (formula[end] === char) {
            end++
            break
          } else {
            end++
          }
        }
      }

      out += formula.slice(i, end)
      i = end
      continue
    }

    plain += char
    i++
  }

  return out + change(plain)
}

/** Excel's text for a formula as Univer keeps it: prefixes gone, an "=" in front. */
export function formulaFromExcel(text: string): string {
  const bare = outsideLiterals(text.replace(/^=/, ''), (part) => part.replace(/_xl(?:fn|ws|pm|udf)\./gi, ''))

  return `=${bare}`
}

/** Univer's formula as a file writes it: no "=", and newer functions prefixed. `unitId` references to the workbook itself lose their `[id]`. */
export function formulaToExcel(formula: string, unitId?: string): string {
  const own = unitId ? `[${unitId}]` : null
  const text = formula.replace(/^=/, '')
  const plain = own ? text.split(own).join('') : text

  return outsideLiterals(plain, (part) =>
    part.replace(/(^|[^A-Za-z0-9_.])([A-Za-z][A-Za-z0-9.]*)(\s*\()/g, (whole, before: string, name: string, open: string) => {
      const upper = name.toUpperCase()

      if (WORKSHEET_ONLY.has(upper)) {
        return `${before}_xlfn._xlws.${name}${open}`
      }

      return NEWER.has(upper) ? `${before}_xlfn.${name}${open}` : whole
    })
  )
}

const REFERENCE = /(^|[^A-Za-z0-9_.$])(?:(\$?)([A-Za-z]{1,3}):(\$?)([A-Za-z]{1,3})|(\$?)(\d{1,7}):(\$?)(\d{1,7})|(\$?)([A-Za-z]{1,3})(\$?)(\d{1,7}))(?![A-Za-z0-9_(!])/g

/** A formula with its relative references moved `rows` down and `columns` across; one moved off the sheet becomes #REF!. */
export function slideFormula(formula: string, rows: number, columns: number): string {
  if (!rows && !columns) {
    return formula
  }

  const column = (absolute: string, name: string): string | null => {
    const index = absolute ? columnIndex(name) : columnIndex(name) + columns

    return index >= 0 && index < MAX_COLUMNS ? `${absolute}${columnName(index)}` : null
  }
  const row = (absolute: string, digits: string): string | null => {
    const index = absolute ? Number(digits) - 1 : Number(digits) - 1 + rows

    return index >= 0 && index < MAX_ROWS ? `${absolute}${index + 1}` : null
  }

  return outsideLiterals(formula, (part) =>
    part.replace(REFERENCE, (whole, before: string, ...groups: string[]) => {
      const [c1$, c1, c2$, c2, r1$, r1, r2$, r2, cell$c, cellColumn, cell$r, cellRow] = groups

      if (c1 !== undefined) {
        const [left, right] = [column(c1$, c1), column(c2$, c2)]

        return left && right ? `${before}${left}:${right}` : `${before}#REF!`
      }

      if (r1 !== undefined) {
        const [top, bottom] = [row(r1$, r1), row(r2$, r2)]

        return top && bottom ? `${before}${top}:${bottom}` : `${before}#REF!`
      }

      if (columnIndex(cellColumn) >= MAX_COLUMNS) {
        return whole
      }

      const [x, y] = [column(cell$c, cellColumn), row(cell$r, cellRow)]

      return x && y ? `${before}${x}${y}` : `${before}#REF!`
    })
  )
}
