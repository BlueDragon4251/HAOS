/*
 * Herald Slides' deck: slides holding text boxes and shapes, measured in points on a 16:9 page of
 * 960 by 540, as PowerPoint measures its slides. A deck is plain data, replaced on every change, so
 * undo is a step back to an earlier deck; it is drawn by the Herald Canvas engine (render.ts) at
 * whatever size it is shown.
 */

export const SLIDE_SIZE = { width: 960, height: 540 } as const

export type Align = 'left' | 'center' | 'right'

interface Box {
  id: string
  x: number
  y: number
  width: number
  height: number
}

export interface TextBox extends Box {
  kind: 'text'
  text: string
  /** Points. */
  size: number
  bold: boolean
  italic: boolean
  color: string
  align: Align
  /** Shown in the editor while the box is empty ("Click to add title"); never drawn. */
  placeholder?: string
}

export interface ShapeBox extends Box {
  kind: 'shape'
  shape: 'rectangle' | 'ellipse'
  fill: string
  /** Corner radius in points, for rectangles. */
  radius: number
}

export type SlideElement = TextBox | ShapeBox

export interface Slide {
  id: string
  background: string
  elements: SlideElement[]
  notes: string
}

export interface DeckTheme {
  font: string
  text: string
  accent: string
  background: string
}

export interface Deck {
  id: string
  title: string
  theme: DeckTheme
  slides: Slide[]
}

export type Layout = 'title' | 'title-body' | 'blank'

export const LAYOUT_NAMES: Record<Layout, string> = { title: 'Title slide', 'title-body': 'Title and text', blank: 'Blank' }

export const DEFAULT_THEME: DeckTheme = { font: 'Helvetica', text: '#1b2340', accent: '#2f7dff', background: '#ffffff' }

let counter = 0
export const newId = (prefix: string): string => `${prefix}-${(++counter).toString(36)}${Math.random().toString(36).slice(2, 7)}`

export function textBox(patch: Partial<TextBox> & Pick<TextBox, 'x' | 'y' | 'width' | 'height'>, theme: DeckTheme = DEFAULT_THEME): TextBox {
  return { id: newId('text'), kind: 'text', text: '', size: 24, bold: false, italic: false, color: theme.text, align: 'left', ...patch }
}

export function shapeBox(patch: Partial<ShapeBox> & Pick<ShapeBox, 'x' | 'y' | 'width' | 'height'>, theme: DeckTheme = DEFAULT_THEME): ShapeBox {
  return { id: newId('shape'), kind: 'shape', shape: 'rectangle', fill: theme.accent, radius: 0, ...patch }
}

/** A slide with the boxes a layout puts on it. */
export function slideWith(layout: Layout, theme: DeckTheme = DEFAULT_THEME): Slide {
  const { width } = SLIDE_SIZE
  const elements: SlideElement[] =
    layout === 'title'
      ? [
          textBox({ x: 80, y: 170, width: width - 160, height: 90, size: 48, bold: true, align: 'center', placeholder: 'Click to add a title' }, theme),
          textBox({ x: 80, y: 280, width: width - 160, height: 60, size: 24, align: 'center', placeholder: 'Click to add a subtitle' }, theme)
        ]
      : layout === 'title-body'
        ? [textBox({ x: 60, y: 40, width: width - 120, height: 70, size: 36, bold: true, placeholder: 'Click to add a title' }, theme), textBox({ x: 60, y: 130, width: width - 120, height: 360, size: 22, placeholder: 'Click to add text' }, theme)]
        : []

  return { id: newId('slide'), background: theme.background, elements, notes: '' }
}

export function newDeck(title: string, id = newId('deck')): Deck {
  return { id, title, theme: DEFAULT_THEME, slides: [slideWith('title')] }
}

const withSlide = (deck: Deck, slideId: string, change: (slide: Slide) => Slide): Deck => ({ ...deck, slides: deck.slides.map((slide) => (slide.id === slideId ? change(slide) : slide)) })

/** A new slide after `afterId` (at the end without one). */
export function addSlide(deck: Deck, layout: Layout, afterId?: string | null): { deck: Deck; slideId: string } {
  const slide = slideWith(layout, deck.theme)
  const index = afterId ? deck.slides.findIndex((entry) => entry.id === afterId) + 1 : deck.slides.length
  const slides = [...deck.slides]
  slides.splice(index > 0 ? index : slides.length, 0, slide)

  return { deck: { ...deck, slides }, slideId: slide.id }
}

/** The deck without a slide; the last slide stays, emptied, since a deck has at least one. */
export function removeSlide(deck: Deck, slideId: string): Deck {
  if (deck.slides.length === 1) {
    return { ...deck, slides: [slideWith('blank', deck.theme)] }
  }

  return { ...deck, slides: deck.slides.filter((slide) => slide.id !== slideId) }
}

export function duplicateSlide(deck: Deck, slideId: string): { deck: Deck; slideId: string } {
  const index = deck.slides.findIndex((slide) => slide.id === slideId)

  if (index < 0) {
    return { deck, slideId }
  }

  const source = deck.slides[index]
  const copy: Slide = { ...source, id: newId('slide'), elements: source.elements.map((element) => ({ ...element, id: newId(element.kind) })) }
  const slides = [...deck.slides]
  slides.splice(index + 1, 0, copy)

  return { deck: { ...deck, slides }, slideId: copy.id }
}

export function moveSlide(deck: Deck, slideId: string, toIndex: number): Deck {
  const from = deck.slides.findIndex((slide) => slide.id === slideId)

  if (from < 0) {
    return deck
  }

  const slides = [...deck.slides]
  const [slide] = slides.splice(from, 1)
  slides.splice(Math.max(0, Math.min(slides.length, toIndex)), 0, slide)

  return { ...deck, slides }
}

/** The smallest box an element keeps, in points. */
export const MIN_SIDE = 8

/** A box kept at least partly on its slide and no smaller than MIN_SIDE. */
export function clampBox<T extends Box>(element: T): T {
  const width = Math.max(MIN_SIDE, element.width)
  const height = Math.max(MIN_SIDE, element.height)
  const x = Math.min(SLIDE_SIZE.width - MIN_SIDE, Math.max(MIN_SIDE - width, element.x))
  const y = Math.min(SLIDE_SIZE.height - MIN_SIDE, Math.max(MIN_SIDE - height, element.y))

  return { ...element, x, y, width, height }
}

export function addElement(deck: Deck, slideId: string, element: SlideElement): Deck {
  return withSlide(deck, slideId, (slide) => ({ ...slide, elements: [...slide.elements, clampBox(element)] }))
}

export function updateElement(deck: Deck, slideId: string, elementId: string, patch: Partial<TextBox> | Partial<ShapeBox>): Deck {
  return withSlide(deck, slideId, (slide) => ({ ...slide, elements: slide.elements.map((element) => (element.id === elementId ? clampBox({ ...element, ...patch } as SlideElement) : element)) }))
}

export function removeElement(deck: Deck, slideId: string, elementId: string): Deck {
  return withSlide(deck, slideId, (slide) => ({ ...slide, elements: slide.elements.filter((element) => element.id !== elementId) }))
}

/** An element moved to the front or back of its slide. */
export function arrangeElement(deck: Deck, slideId: string, elementId: string, to: 'front' | 'back'): Deck {
  return withSlide(deck, slideId, (slide) => {
    const element = slide.elements.find((entry) => entry.id === elementId)
    const rest = slide.elements.filter((entry) => entry.id !== elementId)

    return element ? { ...slide, elements: to === 'front' ? [...rest, element] : [element, ...rest] } : slide
  })
}

export const setNotes = (deck: Deck, slideId: string, notes: string): Deck => withSlide(deck, slideId, (slide) => ({ ...slide, notes }))

export const findSlide = (deck: Deck, slideId: string | null | undefined): Slide | undefined => deck.slides.find((slide) => slide.id === slideId)

/** Undo and redo over whole decks, each step with the name the Edit menu shows. */
export class DeckHistory {
  private past: { deck: Deck; label: string }[] = []
  private future: { deck: Deck; label: string }[] = []

  constructor(
    public present: Deck,
    private readonly limit = 200
  ) {}

  commit(next: Deck, label: string): void {
    if (next === this.present) {
      return
    }

    this.past.push({ deck: this.present, label })
    this.past.splice(0, Math.max(0, this.past.length - this.limit))
    this.future = []
    this.present = next
  }

  /** Start over from `deck` (a version loaded from disk). */
  reset(deck: Deck): void {
    this.past = []
    this.future = []
    this.present = deck
  }

  undo(): string | null {
    const step = this.past.pop()

    if (!step) {
      return null
    }

    this.future.push({ deck: this.present, label: step.label })
    this.present = step.deck

    return step.label
  }

  redo(): string | null {
    const step = this.future.pop()

    if (!step) {
      return null
    }

    this.past.push({ deck: this.present, label: step.label })
    this.present = step.deck

    return step.label
  }

  get canUndo(): boolean {
    return this.past.length > 0
  }

  get canRedo(): boolean {
    return this.future.length > 0
  }
}
