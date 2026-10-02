import { describe, expect, it } from 'vitest'
import { trimAround } from './view-avoid.ts'

describe('trimAround', () => {
  const view = { x: 100, y: 100, width: 600, height: 500 }

  it('stops the view above a pill at its bottom and below a caption at its top', () => {
    expect(trimAround(view, [{ top: 520, bottom: 580, left: 300, right: 800 }])).toEqual({ x: 100, y: 100, width: 600, height: 412 })
    expect(trimAround(view, [{ top: 90, bottom: 130, left: 300, right: 500 }])).toEqual({ x: 100, y: 138, width: 600, height: 462 })
  })

  it('ignores overlays beside the view', () => {
    expect(trimAround(view, [{ top: 520, bottom: 580, left: 720, right: 900 }])).toEqual(view)
  })
})
