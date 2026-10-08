import { type Deck, DeckHistory, findSlide, type Slide } from './deck.ts'

/*
 * One open deck in the editor: its history, the slide in front, what is selected and what is being
 * typed into. A drag shows its deck as a preview and becomes one step when it ends.
 */
export class SlidesDocument {
  readonly history: DeckHistory
  slideId: string
  selected: string | null = null
  editing: string | null = null
  /** A deck shown while a drag is under way, not yet a step. */
  preview: Deck | null = null
  revision = 0
  private readonly listeners = new Set<() => void>()

  constructor(
    deck: Deck,
    private readonly onEdit: () => void
  ) {
    this.history = new DeckHistory(deck)
    this.slideId = deck.slides[0]?.id ?? ''
  }

  get deck(): Deck {
    return this.preview ?? this.history.present
  }

  get slide(): Slide {
    return findSlide(this.deck, this.slideId) ?? this.deck.slides[0]
  }

  get index(): number {
    return Math.max(0, this.deck.slides.findIndex((slide) => slide.id === this.slide.id))
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)

    return () => this.listeners.delete(listener)
  }

  private changed(): void {
    this.revision++
    this.listeners.forEach((listener) => listener())
  }

  /** Keep the slide in front and the selection pointing at things that exist. */
  private settle(): void {
    if (!findSlide(this.deck, this.slideId)) {
      this.slideId = this.deck.slides[Math.min(this.index, this.deck.slides.length - 1)]?.id ?? this.deck.slides[0].id
    }

    const ids = new Set(this.slide.elements.map((element) => element.id))

    if (this.selected && !ids.has(this.selected)) {
      this.selected = null
    }

    if (this.editing && !ids.has(this.editing)) {
      this.editing = null
    }
  }

  commit(next: Deck, label: string, focus?: { slideId?: string; selected?: string | null }): void {
    this.preview = null
    this.history.commit(next, label)

    if (focus?.slideId) {
      this.slideId = focus.slideId
    }

    if (focus && 'selected' in focus) {
      this.selected = focus.selected ?? null
    }

    this.settle()
    this.changed()
    this.onEdit()
  }

  show(preview: Deck | null): void {
    this.preview = preview
    this.changed()
  }

  /** Start over from a deck loaded from disk. */
  reset(deck: Deck): void {
    this.preview = null
    this.history.reset(deck)
    this.settle()
    this.changed()
  }

  undo(): string | null {
    const label = this.history.undo()
    this.settle()
    this.changed()

    if (label) {
      this.onEdit()
    }

    return label
  }

  redo(): string | null {
    const label = this.history.redo()
    this.settle()
    this.changed()

    if (label) {
      this.onEdit()
    }

    return label
  }

  goTo(slideId: string): void {
    if (findSlide(this.deck, slideId) && slideId !== this.slideId) {
      this.slideId = slideId
      this.selected = null
      this.editing = null
      this.changed()
    }
  }

  select(elementId: string | null, editing = false): void {
    this.selected = elementId
    this.editing = editing ? elementId : null
    this.changed()
  }
}
