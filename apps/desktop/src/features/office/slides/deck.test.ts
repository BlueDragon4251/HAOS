import { describe, expect, it } from 'vitest'
import { addElement, addSlide, arrangeElement, clampBox, DeckHistory, duplicateSlide, moveSlide, newDeck, removeElement, removeSlide, shapeBox, SLIDE_SIZE, slideWith, textBox, updateElement } from './deck.ts'

describe('slides', () => {
  it('starts a deck with a title slide whose boxes wait for text', () => {
    const deck = newDeck('Pitch')

    expect(deck.slides).toHaveLength(1)
    expect(deck.slides[0].elements.map((element) => element.kind === 'text' && element.placeholder)).toEqual(['Click to add a title', 'Click to add a subtitle'])
  })

  it('adds a slide after the one asked for, and at the end without one', () => {
    let deck = newDeck('Pitch')
    const first = deck.slides[0].id
    deck = addSlide(deck, 'blank').deck
    const { deck: next, slideId } = addSlide(deck, 'title-body', first)

    expect(next.slides.map((slide) => slide.id)).toEqual([first, slideId, deck.slides[1].id])
    expect(next.slides[1].elements).toHaveLength(2)
  })

  it('keeps one slide when the last is removed', () => {
    const deck = newDeck('Pitch')
    const after = removeSlide(deck, deck.slides[0].id)

    expect(after.slides).toHaveLength(1)
    expect(after.slides[0].id).not.toBe(deck.slides[0].id)
    expect(after.slides[0].elements).toEqual([])
  })

  it('duplicates a slide with new ids, and moves slides', () => {
    const deck = newDeck('Pitch')
    const { deck: doubled, slideId } = duplicateSlide(deck, deck.slides[0].id)

    expect(doubled.slides).toHaveLength(2)
    expect(doubled.slides[1].elements.map((element) => element.id)).not.toEqual(deck.slides[0].elements.map((element) => element.id))
    expect(moveSlide(doubled, slideId, 0).slides[0].id).toBe(slideId)
  })
})

describe('elements', () => {
  it('adds, changes, arranges and removes elements without touching other slides', () => {
    let deck = addSlide(newDeck('Pitch'), 'blank').deck
    const [first, second] = deck.slides
    const box = textBox({ x: 10, y: 10, width: 200, height: 40, text: 'Hello' })
    const shape = shapeBox({ x: 0, y: 0, width: 100, height: 100 })
    deck = addElement(addElement(deck, second.id, box), second.id, shape)
    deck = updateElement(deck, second.id, box.id, { text: 'Hello, Herald', bold: true })

    expect(deck.slides[0]).toBe(first)
    expect(deck.slides[1].elements[0]).toMatchObject({ text: 'Hello, Herald', bold: true })
    expect(arrangeElement(deck, second.id, box.id, 'front').slides[1].elements.map((element) => element.id)).toEqual([shape.id, box.id])
    expect(removeElement(deck, second.id, shape.id).slides[1].elements).toHaveLength(1)
  })

  it('keeps boxes partly on the slide and at least a few points a side', () => {
    expect(clampBox({ id: 'a', x: -500, y: 9999, width: 2, height: 50 })).toEqual({ id: 'a', x: 0, y: SLIDE_SIZE.height - 8, width: 8, height: 50 })
  })

  it('lays out a title and text slide inside the page', () => {
    for (const element of slideWith('title-body').elements) {
      expect(element.x + element.width).toBeLessThanOrEqual(SLIDE_SIZE.width)
      expect(element.y + element.height).toBeLessThanOrEqual(SLIDE_SIZE.height)
    }
  })
})

describe('DeckHistory', () => {
  it('steps back and forward with the labels of the steps', () => {
    const start = newDeck('Pitch')
    const history = new DeckHistory(start)
    const added = addSlide(start, 'blank').deck
    history.commit(added, 'New Slide')

    expect(history.undo()).toBe('New Slide')
    expect(history.present).toBe(start)
    expect(history.canRedo).toBe(true)
    expect(history.redo()).toBe('New Slide')
    expect(history.present).toBe(added)
    expect(history.redo()).toBeNull()
  })

  it('forgets what was undone once something new is done, and ignores a change that changes nothing', () => {
    const start = newDeck('Pitch')
    const history = new DeckHistory(start)
    history.commit(addSlide(start, 'blank').deck, 'New Slide')
    history.undo()
    history.commit(start, 'Nothing')
    history.commit(removeSlide(start, start.slides[0].id), 'Delete Slide')

    expect(history.canRedo).toBe(false)
    expect(history.undo()).toBe('Delete Slide')
    expect(history.canUndo).toBe(false)
  })
})
