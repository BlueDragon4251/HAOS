import { describe, expect, it } from 'vitest'
import { documentFromMarkdown, documentFromText, markdownFromDocument, parseInline, textFromDocument } from './doc-text.ts'
import { blocksFromDocument, CODE_FONT, documentFromBlocks, NAMED_STYLE } from './document.ts'

const ids = { id: 'doc', title: 'Notes' }

describe('documentFromBlocks', () => {
  it("builds Univer's body: paragraphs ending in \\r, the document in \\n, runs over [st, ed)", () => {
    const { body } = documentFromBlocks([{ text: 'Title', runs: [], heading: 1 }, { text: 'Hi there', runs: [{ start: 3, end: 8, bold: true }] }], ids)

    expect(body?.dataStream).toBe('Title\rHi there\r\n')
    expect(body?.paragraphs?.map((paragraph) => paragraph.startIndex)).toEqual([5, 14])
    expect(body?.paragraphs?.[0].paragraphStyle?.namedStyleType).toBe(NAMED_STYLE.heading1)
    expect(body?.textRuns).toEqual([{ st: 9, ed: 14, ts: { bl: 1 } }])
    expect(body?.sectionBreaks?.[0].startIndex).toBe(15)
  })

  it('keeps line breaks and control characters out of a paragraph', () => {
    expect(documentFromBlocks([{ text: 'a\nb\u001Fc', runs: [] }], ids).body?.dataStream).toBe('a bc\r\n')
  })

  it('gives an empty document one empty paragraph', () => {
    expect(documentFromBlocks([], ids).body?.dataStream).toBe('\r\n')
  })
})

describe('plain text', () => {
  it('round-trips lines, empty ones included, with the line endings and BOM of the file', () => {
    const input = '\uFEFFDear Jo,\r\n\r\nSee you soon.\r\n'
    const { document, layout } = documentFromText(input, ids)

    expect(blocksFromDocument(document).blocks.map((block) => block.text)).toEqual(['Dear Jo,', '', 'See you soon.'])
    expect(textFromDocument(document, layout)).toEqual({ text: input, losses: [] })
  })

  it('says formatting is not saved when there is some', () => {
    const document = documentFromBlocks([{ text: 'Plan', runs: [], heading: 1 }], ids)

    expect(textFromDocument(document).losses).toEqual(['Formatting (headings, lists, bold, italic and fonts) is not saved in plain text.'])
  })
})

describe('parseInline', () => {
  it('reads bold, italic, both and code', () => {
    expect(parseInline('a **b** *c* ***d*** `e`')).toEqual({
      text: 'a b c d e',
      runs: [
        { start: 2, end: 3, bold: true, italic: false },
        { start: 4, end: 5, bold: false, italic: true },
        { start: 6, end: 7, bold: true, italic: true },
        { start: 8, end: 9, code: true }
      ]
    })
  })

  it('leaves what is not emphasis as it is written', () => {
    expect(parseInline('snake_case_name and 2 * 3 * 4 and [a link](https://example.com)')).toEqual({ text: 'snake_case_name and 2 * 3 * 4 and [a link](https://example.com)', runs: [] })
  })
})

describe('Markdown', () => {
  it('reads headings, lists, emphasis and code blocks', () => {
    const { document, notes } = documentFromMarkdown('# Plan\n\nWe **ship** on\nFriday.\n\n- one\n  - two\n1. first\n\n```js\nconst a = 1\n```\n', ids)
    const { blocks } = blocksFromDocument(document)

    expect(blocks.map((block) => block.text)).toEqual(['Plan', 'We ship on Friday.', 'one', 'two', 'first', 'const a = 1'])
    expect(blocks[0].heading).toBe(1)
    expect(blocks[1].runs).toEqual([{ start: 3, end: 7, bold: true, italic: false, code: false }])
    expect(blocks[3].list).toEqual({ ordered: false, level: 1 })
    expect(blocks[4].list).toEqual({ ordered: true, level: 0 })
    expect(blocks[5].code).toBe(true)
    expect(document.body?.textRuns?.at(-1)?.ts?.ff).toBe(CODE_FONT)
    expect(notes).toEqual(['Lines of a paragraph that were broken in the file are joined.', 'Code blocks are shown as lines of code, without their language.'])
  })

  it('writes the same Markdown back', () => {
    const input = '# Plan\n\nWe **ship** *soon*, `npm run build`.\n\n- one\n  - two\n- three\n\n1. first\n2. second\n\n| a | b |\n| - | - |\n\n> quoted\n\n```\nconst a = 1\n```\n'
    const { document, layout } = documentFromMarkdown(input, ids)

    expect(markdownFromDocument(document, layout)).toEqual({ text: input, losses: [] })
  })

  it('keeps tables, quotes and links as their text, and says so', () => {
    const { document, notes } = documentFromMarkdown('| a | b |\n|---|---|\n\nSee [the site](https://example.com).\n', ids)

    expect(blocksFromDocument(document).blocks.map((block) => block.text)).toEqual(['| a | b |', '|---|---|', 'See [the site](https://example.com).'])
    expect(notes).toEqual(['Tables, quotes and rules are shown as their Markdown text.', 'Links and images are shown as their Markdown text.'])
  })

  it('lists the styles Markdown cannot hold', () => {
    const document = documentFromBlocks([{ text: 'Big', runs: [] }], ids)
    document.body!.textRuns = [{ st: 0, ed: 3, ts: { fs: 28, cl: { rgb: '#ff0000' } } }]

    expect(markdownFromDocument(document).losses).toEqual(['Font sizes, colours, underline and other fonts are not saved in Markdown.'])
  })
})
