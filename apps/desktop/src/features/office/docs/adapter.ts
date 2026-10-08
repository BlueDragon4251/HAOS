import { documentFromMarkdown, documentFromText, markdownFromDocument, spans, textFromDocument, type TextLayout } from '../../../../shared/office/doc-text.ts'
import { type Block, blocksFromDocument, CODE_FONT, documentFromBlocks, type DocumentSnapshot } from '../../../../shared/office/document.ts'
import { decodeText, encodeText, escapeHtml, printPage, unitId } from '../print.ts'
import type { OfficeAdapter } from '../types.ts'

/*
 * Herald Docs' files: Markdown and plain text for now (Word documents come with the format
 * converters), and the print view main turns into a PDF.
 */

function inlineHtml(block: Block): string {
  return spans(block)
    .map((span) => {
      const text = escapeHtml(span.text)

      if (span.code) {
        return `<code>${text}</code>`
      }

      const emphasised = span.italic ? `<em>${text}</em>` : text

      return span.bold ? `<strong>${emphasised}</strong>` : emphasised
    })
    .join('')
}

const CSS = `
@page { size: A4; margin: 0.75in; }
body { font: 11pt Arial, Helvetica, sans-serif; color: #000; line-height: 1.4; margin: 0; }
h1 { font-size: 20pt; margin: 0 0 8pt; } h2 { font-size: 16pt; margin: 14pt 0 6pt; } h3 { font-size: 14pt; margin: 12pt 0 4pt; }
h4, h5 { font-size: 12pt; margin: 10pt 0 4pt; }
p { margin: 0 0 6pt; min-height: 1em; }
ul, ol { margin: 0 0 6pt; padding-left: 18pt; } ul ul, ol ol, ul ol, ol ul { margin-bottom: 0; } li { margin: 0 0 2pt; }
pre { font: 10pt ${CODE_FONT}, monospace; background: #f4f5f7; padding: 6pt 8pt; border-radius: 4pt; white-space: pre-wrap; }
code { font: 10pt ${CODE_FONT}, monospace; }
`

export function printHtml(document: DocumentSnapshot, title: string): string {
  const { blocks } = blocksFromDocument(document)
  const out: string[] = []
  // The lists open around the current item, outermost first: whether each is numbered.
  const lists: boolean[] = []
  const close = (depth: number) => {
    while (lists.length > depth) {
      out.push(lists.pop() ? '</ol>' : '</ul>')
    }
  }

  blocks.forEach((block, index) => {
    if (block.list) {
      const depth = block.list.level + 1
      close(depth)

      if (lists.length === depth && lists[depth - 1] !== block.list.ordered) {
        close(depth - 1)
      }

      while (lists.length < depth) {
        lists.push(block.list.ordered)
        out.push(block.list.ordered ? '<ol>' : '<ul>')
      }

      out.push(`<li>${inlineHtml(block)}</li>`)

      return
    }

    close(0)

    if (block.code) {
      out.push(`${blocks[index - 1]?.code ? '\n' : '<pre>'}${escapeHtml(block.text)}${blocks[index + 1]?.code ? '' : '</pre>'}`)
    } else if (block.heading) {
      out.push(`<h${block.heading}>${inlineHtml(block)}</h${block.heading}>`)
    } else {
      out.push(`<p>${inlineHtml(block)}</p>`)
    }
  })

  close(0)

  return printPage(title, CSS, out.join(''))
}

export const docsAdapter: OfficeAdapter<DocumentSnapshot> = {
  app: 'docs',
  defaultFormat: '.md',
  blank: (name) => documentFromBlocks([], { id: unitId('doc'), title: name }),
  read: async (bytes, extension, name) => {
    const { text, notes } = decodeText(bytes)
    const options = { id: unitId('doc'), title: name }
    const result = extension === '.txt' ? documentFromText(text, options) : documentFromMarkdown(text, options)

    return { model: result.document, notes: [...notes, ...result.notes], layout: result.layout }
  },
  write: async (model, extension, layout) => {
    const result = extension === '.txt' ? textFromDocument(model, (layout ?? {}) as Partial<TextLayout>) : markdownFromDocument(model, (layout ?? {}) as Partial<TextLayout>)

    return { bytes: encodeText(result.text), losses: result.losses }
  },
  print: async (model, name) => ({ html: printHtml(model, name) })
}
