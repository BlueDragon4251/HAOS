/*
 * The parts of a Univer document snapshot Herald's converters read and write, as plain data, and
 * a document as a list of blocks (paragraphs with their style runs) that text formats are mapped
 * through. In Univer's body every paragraph ends with "\r" and the document with "\n"; a style run
 * covers [st, ed) of that text.
 */

export interface TextStyleSnapshot {
  bl?: number
  it?: number
  ff?: string
  fs?: number
  ul?: { s?: number }
  st?: { s?: number }
  cl?: { rgb?: string }
  [key: string]: unknown
}

export interface TextRunSnapshot {
  st: number
  ed: number
  ts?: TextStyleSnapshot
}

export interface ParagraphSnapshot {
  startIndex: number
  paragraphId?: string
  paragraphStyle?: { namedStyleType?: number; [key: string]: unknown }
  bullet?: { listType: string; listId: string; nestingLevel: number; [key: string]: unknown }
  [key: string]: unknown
}

export interface DocumentBody {
  dataStream: string
  paragraphs?: ParagraphSnapshot[]
  textRuns?: TextRunSnapshot[]
  sectionBreaks?: { startIndex: number; sectionId?: string; [key: string]: unknown }[]
  [key: string]: unknown
}

export interface DocumentSnapshot {
  id: string
  title?: string
  body?: DocumentBody
  documentStyle?: Record<string, unknown>
  [key: string]: unknown
}

/** Univer's named paragraph styles. */
export const NAMED_STYLE = { normal: 1, title: 2, subtitle: 3, heading1: 4, heading5: 8 } as const

/** Univer's A4 page in its pixels (96 a inch), with the margins it gives a new document. */
export const PAGE = { width: 794, height: 1124, margin: 72 } as const

/** The monospace face Herald gives code. */
export const CODE_FONT = 'Menlo'

export interface InlineRun {
  start: number
  end: number
  bold?: boolean
  italic?: boolean
  code?: boolean
}

export interface Block {
  text: string
  runs: InlineRun[]
  /** 1 to 5; titles are 1 and subtitles 2. */
  heading?: number
  list?: { ordered: boolean; level: number }
  /** A line of a code block. */
  code?: boolean
}

let counter = 0
const nextId = (prefix: string): string => `${prefix}${(++counter).toString(36).padStart(4, '0')}${Math.random().toString(36).slice(2, 8)}`

/** Control characters Univer gives meanings of its own (paragraphs, sections, tables, custom ranges). */
const CONTROL = /[\u0000-\u0008\u000B-\u001F\u007F]/g

export const cleanText = (text: string): string => text.replace(/\r\n?|\n/g, ' ').replace(CONTROL, '')

const runStyle = (run: InlineRun): TextStyleSnapshot => ({ ...(run.bold ? { bl: 1 } : {}), ...(run.italic ? { it: 1 } : {}), ...(run.code ? { ff: CODE_FONT } : {}) })

export function documentFromBlocks(blocks: readonly Block[], options: { id: string; title: string }): DocumentSnapshot {
  const list = blocks.length ? blocks : [{ text: '', runs: [] }]
  const paragraphs: ParagraphSnapshot[] = []
  const textRuns: TextRunSnapshot[] = []
  const listIds = { bullet: nextId('list_'), ordered: nextId('list_') }
  let dataStream = ''

  for (const block of list) {
    const start = dataStream.length
    dataStream += `${cleanText(block.text)}\r`
    const runs = block.code ? [{ start: 0, end: block.text.length, code: true }] : block.runs

    for (const run of runs) {
      const style = runStyle(run)

      if (run.end > run.start && Object.keys(style).length) {
        textRuns.push({ st: start + run.start, ed: start + Math.min(run.end, block.text.length), ts: style })
      }
    }

    const paragraph: ParagraphSnapshot = { startIndex: dataStream.length - 1, paragraphId: nextId('para_') }

    if (block.heading) {
      paragraph.paragraphStyle = { namedStyleType: NAMED_STYLE.heading1 + Math.min(4, Math.max(0, block.heading - 1)) }
    }

    if (block.list) {
      paragraph.bullet = { listType: block.list.ordered ? 'ORDER_LIST' : 'BULLET_LIST', listId: block.list.ordered ? listIds.ordered : listIds.bullet, nestingLevel: block.list.level }
    }

    paragraphs.push(paragraph)
  }

  dataStream += '\n'

  return {
    id: options.id,
    title: options.title,
    body: { dataStream, paragraphs, textRuns, sectionBreaks: [{ startIndex: dataStream.length - 1, sectionId: nextId('sect_') }] },
    documentStyle: { documentFlavor: 1, pageSize: { width: PAGE.width, height: PAGE.height }, marginTop: PAGE.margin, marginBottom: PAGE.margin, marginLeft: PAGE.margin, marginRight: PAGE.margin }
  }
}

const isCodeFont = (font: string | undefined): boolean => Boolean(font) && /mono|menlo|courier|consolas|code/i.test(font!)

/**
 * The document without the text colour Univer's editor gives what is typed: the theme's
 * "automatic" colour, written out as a colour. It means no colour, and a saved file says so.
 */
export function withoutAutomaticColor(document: DocumentSnapshot, automatic: string): DocumentSnapshot {
  const runs = document.body?.textRuns

  if (!runs?.length) {
    return document
  }

  const textRuns = runs
    .map((run) => {
      if (typeof run.ts?.cl?.rgb !== 'string' || run.ts.cl.rgb.toLowerCase() !== automatic.toLowerCase()) {
        return run
      }

      const { cl: _automatic, ...ts } = run.ts

      return { ...run, ts }
    })
    .filter((run) => Object.keys(run.ts ?? {}).length > 0)

  return { ...document, body: { ...document.body!, textRuns } }
}

/** A document's paragraphs as blocks, with the extra styles Herald found and the formats cannot keep. */
export function blocksFromDocument(document: DocumentSnapshot): { blocks: Block[]; extras: Set<string> } {
  const body = document.body ?? { dataStream: '\r\n' }
  const stream = body.dataStream ?? ''
  const paragraphs = [...(body.paragraphs ?? [])].sort((a, b) => a.startIndex - b.startIndex)
  const runs = body.textRuns ?? []
  const blocks: Block[] = []
  const extras = new Set<string>()
  let from = 0

  for (const paragraph of paragraphs) {
    const end = paragraph.startIndex
    // Characters Univer uses for its own markers (tables, custom ranges) are not text.
    const text = stream.slice(from, end).replace(CONTROL, '')
    const block: Block = { text, runs: [] }

    for (const run of runs) {
      if (run.ed <= from || run.st >= end) {
        continue
      }

      const style = run.ts ?? {}
      const inline: InlineRun = { start: Math.max(0, run.st - from), end: Math.min(text.length, run.ed - from), bold: style.bl === 1, italic: style.it === 1, code: isCodeFont(style.ff) }

      if (inline.bold || inline.italic || inline.code) {
        block.runs.push(inline)
      }

      if (style.fs || style.cl || style.ul?.s || style.st?.s || (style.ff && !inline.code)) {
        extras.add('character')
      }
    }

    const named = paragraph.paragraphStyle?.namedStyleType

    if (named === NAMED_STYLE.title) {
      block.heading = 1
    } else if (named === NAMED_STYLE.subtitle) {
      block.heading = 2
    } else if (named && named >= NAMED_STYLE.heading1 && named <= NAMED_STYLE.heading5) {
      block.heading = named - NAMED_STYLE.heading1 + 1
    }

    if (paragraph.bullet) {
      block.list = { ordered: /ORDER/.test(paragraph.bullet.listType), level: Math.max(0, paragraph.bullet.nestingLevel ?? 0) }
    }

    const rest = Object.keys(paragraph.paragraphStyle ?? {}).filter((key) => key !== 'namedStyleType')

    if (rest.some((key) => !['lineSpacing', 'spaceAbove', 'spaceBelow'].includes(key))) {
      extras.add('paragraph')
    }

    block.code = Boolean(text) && block.runs.length === 1 && block.runs[0].code === true && block.runs[0].start === 0 && block.runs[0].end >= text.length

    if (block.code) {
      block.runs = []
    }

    blocks.push(block)
    from = end + 1
  }

  if ((body.tables as unknown[] | undefined)?.length || (body.customBlocks as unknown[] | undefined)?.length) {
    extras.add('objects')
  }

  return { blocks, extras }
}
