import { describe, expect, it } from 'vitest'
import { guideAxisFrom } from '../agent-model.ts'
import type { DocState } from './document.ts'
import { guideNear, layoutGuides, onCanvas, positionFrom, withGuideMoved, withGuides, withoutGuides } from './guides.ts'
import { linesOf, nearest, rulerSteps, type SnapLine, smartGuides, snapBox, snapToLines } from './snapping.ts'

const box = (x: number, y: number, width: number, height: number) => ({ x, y, width, height })
const emptyState = (): DocState => ({ width: 1000, height: 600, resolution: 72, layers: [], activeLayerId: null, guides: [], selection: null })

describe('snapping', () => {
  const lines = linesOf({ width: 1000, height: 600 }, [{ axis: 'vertical', position: 120 }], [box(400, 100, 200, 100)])

  it('offers the canvas edges and centre, guides and boxes’ edges and centres', () => {
    const xs = lines.filter((line) => line.axis === 'x').map((line) => `${line.kind}:${line.value}`)
    expect(xs).toEqual(['canvas:0', 'canvas:500', 'canvas:1000', 'guide:120', 'layer:400', 'layer:500', 'layer:600'])
    expect(lines.filter((line) => line.axis === 'y').map((line) => line.value)).toEqual([0, 300, 600, 100, 150, 200])
  })

  it('pulls a point onto the nearest line within reach, each way on its own', () => {
    expect(snapToLines([123, 297], lines, 6).delta).toEqual([-3, 3])
    expect(snapToLines([140, 260], lines, 6).delta).toEqual([0, 0])
  })

  it('prefers a guide when two lines are as close', () => {
    const tie: SnapLine[] = [
      { axis: 'x', value: 10, kind: 'layer' },
      { axis: 'x', value: 10, kind: 'guide' }
    ]
    expect(nearest([12], tie, 5)?.line.kind).toBe('guide')
  })

  it('snaps a moving box by an edge or its centre', () => {
    // Its left edge is 4 from the guide at 120; its centre is 7 from the canvas centre.
    const moved = snapBox(box(116, 400, 50, 20), lines, 6)
    expect(moved.delta[0]).toBe(4)
    expect(moved.lines[0]).toMatchObject({ kind: 'guide', value: 120 })
    const centred = snapBox(box(470, 285, 50, 20), lines, 6)
    expect(centred.delta).toEqual([5, 5])
  })

  it('finds what a moving box lines up with, and its gaps to the neighbours it faces', () => {
    const others = [box(0, 0, 100, 100), box(300, 0, 100, 50)]
    const { lines: guides, gaps } = smartGuides(box(150, 0, 100, 100), others, box(0, 0, 1000, 600))
    expect(guides.find((line) => line.axis === 'y' && line.at === 0)).toMatchObject({ from: 0, to: 1000 })
    expect(guides.find((line) => line.axis === 'y' && line.at === 100)).toMatchObject({ from: 0, to: 250 })
    expect(gaps.map((gap) => [gap.axis, gap.from, gap.to, gap.distance])).toEqual([
      ['x', 100, 150, 50],
      ['x', 250, 300, 50]
    ])
  })

  it('spaces ruler labels for the zoom', () => {
    expect(rulerSteps(1)).toEqual({ step: 100, parts: 10 })
    expect(rulerSteps(0.25)).toEqual({ step: 500, parts: 10 })
    expect(rulerSteps(8).step).toBe(10)
    expect(rulerSteps(64).step).toBe(1)
  })
})

describe('guides', () => {
  it('adds, moves and removes guides, never twice at one place', () => {
    const { state, added } = withGuides(emptyState(), [
      { axis: 'vertical', position: 500 },
      { axis: 'vertical', position: 500 },
      { axis: 'horizontal', position: 120.456 }
    ])
    expect(added.map((guide) => [guide.axis, guide.position])).toEqual([
      ['vertical', 500],
      ['horizontal', 120.46]
    ])
    expect(withGuides(state, [{ axis: 'vertical', position: 500 }]).state).toBe(state)
    const moved = withGuideMoved(state, added[0].id, 640)
    expect(moved.guides[0].position).toBe(640)
    expect(withoutGuides(moved, [added[0].id]).guides).toHaveLength(1)
    expect(guideNear(state, 'horizontal', 121)?.id).toBe(added[1].id)
    expect(guideNear(state, 'horizontal', 125)).toBeUndefined()
  })

  it('reads positions in pixels or percentages, and knows when one is off the canvas', () => {
    expect(positionFrom('50%', 1000)).toBe(500)
    expect(positionFrom(320, 1000)).toBe(320)
    expect(positionFrom(undefined, 1000)).toBeUndefined()
    expect(() => positionFrom('middle', 1000)).toThrow(/percentage/)
    expect(onCanvas({ width: 1000, height: 600 }, 'horizontal', 650)).toBe(false)
    expect(onCanvas({ width: 1000, height: 600 }, 'vertical', 650)).toBe(true)
  })

  it('lays out margins, columns with gutters and centre lines', () => {
    const guides = layoutGuides({ width: 1000, height: 600 }, { margins: 50, columns: 3, gutter: 30, center: true })
    const vertical = guides.filter((guide) => guide.axis === 'vertical').map((guide) => guide.position)
    // Three columns of 280 in the 900 between the margins, 30 apart.
    expect(vertical).toEqual([50, 950, 330, 360, 640, 670, 500])
    expect(guides.filter((guide) => guide.axis === 'horizontal').map((guide) => guide.position)).toEqual([50, 550, 300])
    expect(() => layoutGuides({ width: 100, height: 100 }, { margins: 60 })).toThrow(/leave nothing/)
    expect(() => layoutGuides({ width: 100, height: 100 }, { columns: 10, gutter: 20 })).toThrow(/do not fit/)
  })

  it('reads which way a guide runs', () => {
    expect(guideAxisFrom('Vertical')).toBe('vertical')
    expect(guideAxisFrom('row')).toBe('horizontal')
    expect(() => guideAxisFrom('diagonal')).toThrow(/axis is/)
  })
})
