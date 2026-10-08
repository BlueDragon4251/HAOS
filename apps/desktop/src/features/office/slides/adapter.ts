import { escapeHtml, printPage } from '../print.ts'
import type { OfficeAdapter } from '../types.ts'
import { type Deck, newDeck } from './deck.ts'

/*
 * Herald Slides' files. Decks open and save as PowerPoint files once the format converters come;
 * until then a deck is exported as a PDF, one slide a page.
 */

/** Slides print at 1920 by 1080, twice their size in points. */
const PRINT_SCALE = 2

export const slidesAdapter: OfficeAdapter<Deck> = {
  app: 'slides',
  defaultFormat: '.pptx',
  blank: (name) => newDeck(name),
  read: async () => {
    throw new Error('Herald Slides opens PowerPoint files once the format converters come')
  },
  write: async () => {
    throw new Error('Herald Slides saves PowerPoint files once the format converters come')
  },
  print: async (deck, name) => {
    const { slidePng } = await import('./render.ts')
    const pages: string[] = []

    for (const slide of deck.slides) {
      pages.push(`<img src="${await slidePng(deck, slide, PRINT_SCALE)}" alt="">`)
    }

    const css = '@page { size: 13.333in 7.5in; margin: 0; } body { margin: 0; } img { display: block; width: 13.333in; height: 7.5in; page-break-after: always; break-after: page; } img:last-child { page-break-after: auto; break-after: auto; }'

    return { html: printPage(name, css, pages.join('') || `<p>${escapeHtml(name)}</p>`), landscape: true }
  }
}
