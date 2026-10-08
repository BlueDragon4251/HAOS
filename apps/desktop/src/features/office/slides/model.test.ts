import { describe, expect, it, vi } from 'vitest'
import { addElement, addSlide, newDeck, removeSlide, shapeBox, updateElement } from './deck.ts'
import { SlidesDocument } from './model.ts'

describe('SlidesDocument', () => {
  it('shows a drag as a preview and keeps it as one step when it ends', () => {
    const edited = vi.fn()
    const deck = newDeck('Pitch')
    const doc = new SlidesDocument(deck, edited)
    const box = deck.slides[0].elements[0]

    doc.show(updateElement(deck, doc.slideId, box.id, { x: 10 }))
    doc.show(updateElement(deck, doc.slideId, box.id, { x: 20 }))
    expect(doc.deck.slides[0].elements[0].x).toBe(20)
    expect(doc.history.canUndo).toBe(false)
    expect(edited).not.toHaveBeenCalled()

    doc.commit(doc.preview!, 'Move', { selected: box.id })
    expect(doc.preview).toBeNull()
    expect(doc.selected).toBe(box.id)
    expect(edited).toHaveBeenCalledOnce()
    expect(doc.undo()).toBe('Move')
    expect(doc.deck.slides[0].elements[0].x).toBe(box.x)
  })

  it('moves to a new slide, and back to a slide that still exists after an undo', () => {
    const doc = new SlidesDocument(newDeck('Pitch'), () => {})
    const first = doc.slideId
    const { deck, slideId } = addSlide(doc.history.present, 'blank')
    doc.commit(deck, 'New Slide', { slideId })

    expect(doc.index).toBe(1)
    doc.undo()
    expect(doc.slideId).toBe(first)
  })

  it('drops a selection whose element is gone', () => {
    const doc = new SlidesDocument(newDeck('Pitch'), () => {})
    const shape = shapeBox({ x: 0, y: 0, width: 10, height: 10 })
    doc.commit(addElement(doc.history.present, doc.slideId, shape), 'New Shape', { selected: shape.id })

    expect(doc.selected).toBe(shape.id)
    doc.undo()
    expect(doc.selected).toBeNull()
  })

  it('starts over from a deck loaded from disk', () => {
    const doc = new SlidesDocument(newDeck('Pitch'), () => {})
    doc.commit(removeSlide(doc.history.present, doc.slideId), 'Delete Slide')
    const loaded = newDeck('From disk')
    doc.reset(loaded)

    expect(doc.deck).toBe(loaded)
    expect(doc.history.canUndo).toBe(false)
    expect(doc.slideId).toBe(loaded.slides[0].id)
  })
})
