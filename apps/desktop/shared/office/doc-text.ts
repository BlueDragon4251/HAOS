import { type Block, blocksFromDocument, documentFromBlocks, type DocumentSnapshot, type InlineRun } from './document.ts'

/*
 * Plain text and Markdown as Herald Docs documents and back. Plain text keeps its lines as
 * paragraphs. Markdown keeps headings, lists, bold, italic, code and code blocks; what Herald Docs
 * has no style for (links, tables, quotes) stays as its Markdown text, so saving writes it back as
 * it was.
 */

export interface TextLayout {
  eol: '\n' | '\r\n'
  bom: boolean
}

export interface ReadResult {
  document: DocumentSnapshot
  layout: TextLayout
  /** What opening the file approximated. */
  notes: string[]
}

export interface WriteResult {
  text: string
  /** What the format cannot keep of this document. */
  losses: string[]
}

function layoutOf(input: string): { text: string; layout: TextLayout } {
  const bom = input.startsWith('\uFEFF')
  const text = bom ? input.slice(1) : input

  return { text, layout: { eol: /\r\n/.test(text) ? '\r\n' : '\n', bom } }
}

const lines = (text: string): string[] => {
  const all = text.split(/\r\n?|\n/)

  return all.length > 1 && all[all.length - 1] === '' ? all.slice(0, -1) : all
}

const write = (rows: string[], layout: Partial<TextLayout>): string => {
  const eol = layout.eol ?? '\n'

  return `${layout.bom ? '\uFEFF' : ''}${rows.join(eol)}${rows.length ? eol : ''}`
}

// Plain text.

export function documentFromText(input: string, options: { id: string; title: string }): ReadResult {
  const { text, layout } = layoutOf(input)

  return { document: documentFromBlocks(lines(text).map((line) => ({ text: line, runs: [] })), options), layout, notes: [] }
}

export function textFromDocument(document: DocumentSnapshot, layout: Partial<TextLayout> = {}): WriteResult {
  const { blocks, extras } = blocksFromDocument(document)
  const styled = extras.size > 0 || blocks.some((block) => block.heading || block.list || block.code || block.runs.length)

  return { text: write(blocks.map((block) => block.text), layout), losses: styled ? ['Formatting (headings, lists, bold, italic and fonts) is not saved in plain text.'] : [] }
}

// Markdown: inline styles.

/** Bold, italic and code spans in one line of Markdown; everything else stays as it is written. */
export function parseInline(source: string): { text: string; runs: InlineRun[] } {
  const runs: InlineRun[] = []
  let text = ''
  let i = 0

  while (i < source.length) {
    const rest = source.slice(i)
    const code = /^`([^`]+)`/.exec(rest)
    const strong = /^(\*\*\*|___)(?=\S)([\s\S]*?\S)\1/.exec(rest) ?? null
    const bold = strong ? null : /^(\*\*|__)(?=\S)([\s\S]*?\S)\1/.exec(rest)
    const italic = strong || bold ? null : /^(\*|_)(?=\S)([^*_]*?\S)\1(?![*_\w])/.exec(rest)
    // An underscore inside a word (snake_case) is not emphasis.
    const wordInside = source[i] === '_' && /\w/.test(source[i - 1] ?? '')

    if (code) {
      runs.push({ start: text.length, end: text.length + code[1].length, code: true })
      text += code[1]
      i += code[0].length
    } else if (!wordInside && (strong || bold || italic)) {
      const match = (strong ?? bold ?? italic)!
      const inner = parseInline(match[2])
      const offset = text.length

      for (const run of inner.runs) {
        runs.push({ ...run, start: run.start + offset, end: run.end + offset })
      }

      runs.push({ start: offset, end: offset + inner.text.length, bold: Boolean(strong || bold), italic: Boolean(strong || italic) })
      text += inner.text
      i += match[0].length
    } else {
      text += source[i]
      i++
    }
  }

  return { text, runs }
}

/** A run of text with one style, for writing. */
export interface Span {
  text: string
  bold: boolean
  italic: boolean
  code: boolean
}

/** A block's text cut where its style changes. */
export function spans(block: Block): Span[] {
  const cuts = new Set([0, block.text.length])

  for (const run of block.runs) {
    cuts.add(Math.max(0, Math.min(block.text.length, run.start)))
    cuts.add(Math.max(0, Math.min(block.text.length, run.end)))
  }

  const points = [...cuts].sort((a, b) => a - b)
  const out: Span[] = []

  for (let i = 0; i < points.length - 1; i++) {
    const [from, to] = [points[i], points[i + 1]]
    const covering = block.runs.filter((run) => run.start <= from && run.end >= to)
    const span = { text: block.text.slice(from, to), bold: covering.some((run) => run.bold), italic: covering.some((run) => run.italic), code: covering.some((run) => run.code) }
    const last = out[out.length - 1]

    if (last && last.bold === span.bold && last.italic === span.italic && last.code === span.code) {
      last.text += span.text
    } else if (span.text) {
      out.push(span)
    }
  }

  return out
}

/** A span with its markers; spaces stay outside them, where Markdown needs them. */
function marked(span: Span): string {
  if (span.code) {
    return `\`${span.text}\``
  }

  const marker = span.bold && span.italic ? '***' : span.bold ? '**' : span.italic ? '*' : ''
  const match = /^(\s*)([\s\S]*?)(\s*)$/.exec(span.text)!

  return marker && match[2] ? `${match[1]}${marker}${match[2]}${marker}${match[3]}` : span.text
}

export const inlineMarkdown = (block: Block): string => spans(block).map(marked).join('')

// Markdown: blocks.

const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/
const LIST = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/
const FENCE = /^\s*(```|~~~)/

/** Lines that stay as Markdown text, one paragraph each: tables, quotes, rules, HTML. */
const LITERAL = /^\s*(\||>|<|(-{3,}|\*{3,}|_{3,})\s*$)/

export function documentFromMarkdown(input: string, options: { id: string; title: string }): ReadResult {
  const { text, layout } = layoutOf(input)
  const blocks: Block[] = []
  const notes = new Set<string>()
  const source = lines(text)
  let paragraph: string[] = []
  let fence: string | null = null

  const flush = () => {
    if (paragraph.length) {
      if (paragraph.length > 1) {
        notes.add('Lines of a paragraph that were broken in the file are joined.')
      }

      blocks.push(parseInline(paragraph.join(' ')))
      paragraph = []
    }
  }

  for (const line of source) {
    if (fence) {
      if (line.trim().startsWith(fence)) {
        fence = null
      } else {
        blocks.push({ text: line, runs: [], code: true })
      }

      continue
    }

    const fenced = FENCE.exec(line)

    if (fenced) {
      flush()
      fence = fenced[1]
      notes.add('Code blocks are shown as lines of code, without their language.')
      continue
    }

    if (!line.trim()) {
      flush()
      continue
    }

    const heading = HEADING.exec(line)

    if (heading) {
      flush()

      if (heading[1].length > 5) {
        notes.add('Level 6 headings are shown as level 5.')
      }

      blocks.push({ ...parseInline(heading[2]), heading: Math.min(5, heading[1].length) })
      continue
    }

    const item = LIST.exec(line)

    if (item) {
      flush()
      blocks.push({ ...parseInline(item[3]), list: { ordered: /\d/.test(item[2]), level: Math.min(8, Math.floor(item[1].replace(/\t/g, '    ').length / 2)) } })
      continue
    }

    if (LITERAL.test(line)) {
      flush()
      notes.add('Tables, quotes and rules are shown as their Markdown text.')
      blocks.push({ text: line, runs: [] })
      continue
    }

    // A line indented under a list item continues it.
    const previous = blocks[blocks.length - 1]

    if (!paragraph.length && previous?.list && /^\s+\S/.test(line)) {
      const more = parseInline(line.trim())
      const offset = previous.text.length + 1
      previous.text = `${previous.text} ${more.text}`
      previous.runs.push(...more.runs.map((run) => ({ ...run, start: run.start + offset, end: run.end + offset })))
      continue
    }

    if (/\[[^\]]*\]\([^)]*\)/.test(line)) {
      notes.add('Links and images are shown as their Markdown text.')
    }

    paragraph.push(line.trim())
  }

  flush()

  return { document: documentFromBlocks(blocks, options), layout, notes: [...notes] }
}

const isLiteral = (block: Block): boolean => !block.heading && !block.list && !block.code && LITERAL.test(block.text)

export function markdownFromDocument(document: DocumentSnapshot, layout: Partial<TextLayout> = {}): WriteResult {
  const { blocks, extras } = blocksFromDocument(document)
  const out: string[] = []
  const numbers: number[] = []
  let previous: Block | null = null

  blocks.forEach((block, index) => {
    const next = blocks[index + 1]

    if (block.code) {
      if (!previous?.code) {
        if (out.length) {
          out.push('')
        }

        out.push('```')
      }

      out.push(block.text)

      if (!next?.code) {
        out.push('```')
      }

      previous = block

      return
    }

    // Markdown has no empty paragraph: an empty one only separates the blocks around it.
    if (!block.text.trim()) {
      previous = block

      return
    }

    // A list goes on until its kind changes at the top level; tables and quotes until another kind of line.
    const sameList = Boolean(previous?.list && block.list && (block.list.level > 0 || previous.list.level > 0 || previous.list.ordered === block.list.ordered))
    const together = previous && previous.text.trim() && (sameList || (isLiteral(previous) && isLiteral(block) && previous.text.trim()[0] === block.text.trim()[0]))

    if (out.length && !together) {
      out.push('')
    }

    if (block.list) {
      const level = block.list.level
      numbers.length = level + 1
      numbers[level] = block.list.ordered ? (numbers[level] ?? 0) + 1 : 0
      out.push(`${'  '.repeat(level)}${block.list.ordered ? `${numbers[level]}.` : '-'} ${inlineMarkdown(block)}`)
    } else {
      numbers.length = 0
      out.push(block.heading ? `${'#'.repeat(block.heading)} ${inlineMarkdown(block)}` : isLiteral(block) ? block.text : inlineMarkdown(block))
    }

    previous = block
  })

  const losses = [
    ...(extras.has('character') ? ['Font sizes, colours, underline and other fonts are not saved in Markdown.'] : []),
    ...(extras.has('paragraph') ? ['Paragraph alignment, indents and spacing are not saved in Markdown.'] : []),
    ...(extras.has('objects') ? ['Tables and pictures in the document are not saved in Markdown.'] : [])
  ]

  return { text: write(out, layout), losses }
}
