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

const opensLiteral = (char: string | undefined): boolean => char === '"' || char === "'" || char === '['

/** Where a literal starting at `start` ends: a string or quoted sheet name (quotes doubled inside), or a bracketed, possibly nested, structured reference. */
function literalEnd(formula: string, start: number): number {
  const char = formula[start]
  let end = start + 1

  if (char === '[') {
    for (let depth = 1; end < formula.length && depth > 0; end++) {
      depth += formula[end] === '[' ? 1 : formula[end] === ']' ? -1 : 0
    }

    return end
  }

  while (end < formula.length) {
    if (formula[end] === char && formula[end + 1] === char) {
      end += 2
    } else if (formula[end] === char) {
      return end + 1
    } else {
      end++
    }
  }

  return end
}

/** Run `change` on the parts of a formula outside strings, quoted sheet names and structured references. */
function outsideLiterals(formula: string, change: (part: string) => string): string {
  let out = ''
  let plain = ''
  let i = 0

  while (i < formula.length) {
    if (opensLiteral(formula[i])) {
      const end = literalEnd(formula, i)
      out += change(plain) + formula.slice(i, end)
      plain = ''
      i = end
      continue
    }

    plain += formula[i]
    i++
  }

  return out + change(plain)
}

/** Excel's text for a formula as Univer keeps it: prefixes gone, an "=" in front. */
export function formulaFromExcel(text: string): string {
  const bare = outsideLiterals(text.replace(/^=/, ''), (part) => part.replace(/_xl(?:fn|ws|pm|udf)\./gi, ''))

  return `=${bare}`
}

interface Token {
  kind: 'name' | 'literal' | 'other'
  text: string
}

/** A formula as names, literals (text, quoted sheet names, brackets) and the rest, one character at a time. */
function tokens(formula: string): Token[] {
  const out: Token[] = []
  let i = 0

  while (i < formula.length) {
    if (opensLiteral(formula[i])) {
      const end = literalEnd(formula, i)
      out.push({ kind: 'literal', text: formula.slice(i, end) })
      i = end
      continue
    }

    const name = /^[A-Za-z_\\][A-Za-z0-9_.]*/.exec(formula.slice(i, i + 256))

    if (name) {
      out.push({ kind: 'name', text: name[0] })
      i += name[0].length
      continue
    }

    out.push({ kind: 'other', text: formula[i] })
    i++
  }

  return out
}

/** LET and LAMBDA name their parameters with `_xlpm.` in a file, where they are declared and used. */
function withParameterPrefixes(formula: string): string {
  const list = tokens(formula)
  const prefixed = new Set<number>()

  list.forEach((token, start) => {
    const kind = token.kind === 'name' ? token.text.toUpperCase() : ''

    if ((kind !== 'LET' && kind !== 'LAMBDA') || list[start + 1]?.text !== '(') {
      return
    }

    // The call's arguments: token ranges between top-level commas.
    const args: [number, number][] = []
    let depth = 0
    let from = start + 2
    let end = start + 2

    for (; end < list.length; end++) {
      const text = list[end].text

      if (text === '(') {
        depth++
      } else if (text === ')' && depth-- === 0) {
        break
      } else if (text === ',' && depth === 0) {
        args.push([from, end])
        from = end + 1
      }
    }

    args.push([from, end])
    const names = new Set<string>()

    args.slice(0, -1).forEach(([a, b], index) => {
      const words = list.slice(a, b).filter((entry) => entry.text.trim())

      if ((kind === 'LAMBDA' || index % 2 === 0) && words.length === 1 && words[0].kind === 'name') {
        names.add(words[0].text.toUpperCase())
      }
    })

    for (let at = start + 2; at < end; at++) {
      if (list[at].kind === 'name' && names.has(list[at].text.toUpperCase()) && list[at + 1]?.text !== '(' && list[at + 1]?.text !== '!') {
        prefixed.add(at)
      }
    }
  })

  return list.map((token, at) => (prefixed.has(at) ? `_xlpm.${token.text}` : token.text)).join('')
}

/** Univer's formula as a file writes it: no "=", and newer functions prefixed. `unitId` references to the workbook itself lose their `[id]`. */
export function formulaToExcel(formula: string, unitId?: string): string {
  const own = unitId ? `[${unitId}]` : null
  const text = formula.replace(/^=/, '')
  const bare = own ? text.split(own).join('') : text
  const plain = /\b(LET|LAMBDA)\s*\(/i.test(bare) ? withParameterPrefixes(bare) : bare

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
