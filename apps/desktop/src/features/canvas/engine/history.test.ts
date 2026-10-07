import { describe, expect, it } from 'vitest'
import { describeHistory, stepCount, stepThrough } from '../agent-model.ts'
import { blankLayer, CanvasDocument, type DocState, insertLayer } from './document.ts'
import { History, type HistoryEntry } from './history.ts'

const emptyState = (): DocState => ({ width: 40, height: 30, resolution: 72, layers: [], activeLayerId: null, guides: [], selection: null })

/** A step that moves a counter, so undo and redo can be watched. */
function counter(): { value: number; step: (label: string, bytes?: number) => HistoryEntry } {
  const box = { value: 0, step: (label: string, bytes = 10): HistoryEntry => ({ label, bytes, undo: () => box.value--, redo: () => box.value++ }) }

  return box
}

describe('History steps', () => {
  it('lists applied steps, then undone ones in the order redo takes them', () => {
    const history = new History()
    const count = counter()

    for (const label of ['One', 'Two', 'Three']) {
      count.value++
      history.push(count.step(label))
    }

    history.undo()
    history.undo()
    expect(history.steps.map((step) => step.label)).toEqual(['One', 'Two', 'Three'])
    expect(history.applied).toBe(1)
    expect(count.value).toBe(1)
  })

  it('goes back and forward to any step, and a new edit drops the undone ones', () => {
    const history = new History()
    const count = counter()

    for (const label of ['One', 'Two', 'Three', 'Four']) {
      count.value++
      history.push(count.step(label))
    }

    expect(history.goTo(1)).toEqual(['Four', 'Three', 'Two'])
    expect(count.value).toBe(1)
    expect(history.goTo(3)).toEqual(['Two', 'Three'])
    expect(count.value).toBe(3)
    expect(history.goTo(99)).toEqual(['Four'])
    expect(history.goTo(0)).toHaveLength(4)
    expect(count.value).toBe(0)
    count.value++
    history.push(count.step('Fresh'))
    expect(history.steps.map((step) => step.label)).toEqual(['Fresh'])
  })

  it('remembers who made a step, and counts the steps it let go of', () => {
    const history = new History(25)
    const count = counter()
    history.push(count.step('Mine'))
    history.push(count.step('Hermes'))
    history.tagLast('command')
    expect(history.steps.map((step) => step.origin)).toEqual([undefined, 'command'])
    history.push(count.step('Third'))
    expect(history.dropped).toBe(1)
    expect(history.steps[0].label).toBe('Hermes')
  })
})

describe('CanvasDocument history', () => {
  it('goes to a step and back, redrawing once', () => {
    const doc = new CanvasDocument({ state: emptyState(), name: 'Test' })
    doc.commit('New Layer', insertLayer(doc.state, blankLayer('A', 40, 30)))
    doc.commit('New Layer', insertLayer(doc.state, blankLayer('B', 40, 30)))
    const revision = doc.revision
    expect(doc.goTo(0)).toEqual(['New Layer', 'New Layer'])
    expect(doc.state.layers).toHaveLength(0)
    expect(doc.revision).toBe(revision + 1)
    doc.goTo(2)
    expect(doc.state.layers.map((layer) => layer.name)).toEqual(['A', 'B'])
  })

  it('toggles the last state back and forth', () => {
    const doc = new CanvasDocument({ state: emptyState(), name: 'Test' })
    doc.commit('New Layer', insertLayer(doc.state, blankLayer('A', 40, 30)))
    expect(doc.toggleLast()).toBe('New Layer')
    expect(doc.state.layers).toHaveLength(0)
    expect(doc.toggleLast()).toBe('New Layer')
    expect(doc.state.layers).toHaveLength(1)
    expect(doc.toggleLast()).toBe('New Layer')
    expect(doc.state.layers).toHaveLength(0)
  })
})

describe('history for Hermes', () => {
  it('reads a step count, one by default', () => {
    expect(stepCount(undefined)).toBe(1)
    expect(stepCount(3.4)).toBe(3)
    expect(stepCount(5000)).toBe(1000)
    expect(() => stepCount(0)).toThrow(/1 or more/)
  })

  it('steps until the history runs out', () => {
    const doc = new CanvasDocument({ state: emptyState(), name: 'Test' })
    doc.commit('New Layer', insertLayer(doc.state, blankLayer('A', 40, 30)))
    doc.commit('Rename Layer', doc.state)
    doc.commit('Delete Layer', { ...doc.state, layers: [] })
    expect(stepThrough(doc, 'undo', 5)).toEqual(['Delete Layer', 'New Layer'])
    expect(stepThrough(doc, 'redo', 1)).toEqual(['New Layer'])
  })

  it('numbers the steps and marks the undone ones and those a command made', () => {
    const described = describeHistory(
      [
        { id: 4, label: 'Brush' },
        { id: 5, label: 'Add Layer', origin: 'command' },
        { id: 6, label: 'Crop' }
      ],
      2
    )
    expect(described).toEqual([{ step: 1, label: 'Brush' }, { step: 2, label: 'Add Layer', by: 'Hermes or a command' }, { step: 3, label: 'Crop', undone: true }])
  })
})
