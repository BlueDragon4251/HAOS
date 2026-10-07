import { describe, expect, it } from 'vitest'
import { defaultAdjustment } from '../../../../shared/canvas/comp-format.ts'
import { adjustmentLayer, type DocState, folderLayer } from './document.ts'
import { isSoftwareRenderer } from './gpu/gl.ts'
import { covers, planFrame } from './gpu/view.ts'
import { filterReach, frameSize, planTiles, strips, TILE_ALIGN, tileSide } from './tiles.ts'

const doc = (layers: DocState['layers'], width = 4000, height = 3000): DocState => ({ width, height, resolution: 72, layers, activeLayerId: null, guides: [], selection: null })

describe('tiles', () => {
  it('cover an area once, each padded within the frame and starting on the grid', () => {
    const frame = { width: 5000, height: 3000 }
    const tiles = planTiles(frame, { x: 0, y: 0, ...frame }, 2048, 300)
    expect(tiles).toHaveLength(6)

    for (const { inner, padded } of tiles) {
      expect(padded.x % TILE_ALIGN).toBe(0)
      expect(padded.y % TILE_ALIGN).toBe(0)
      expect(padded.x).toBeLessThanOrEqual(Math.max(0, inner.x - 300))
      expect(padded.x + padded.width).toBe(Math.min(frame.width, inner.x + inner.width + 300))
      expect(padded.width).toBeLessThanOrEqual(2048 + 2 * 300 + TILE_ALIGN)
    }

    for (let y = 0; y < frame.height; y += 37) {
      for (let x = 0; x < frame.width; x += 37) {
        expect(tiles.filter(({ inner }) => x >= inner.x && x < inner.x + inner.width && y >= inner.y && y < inner.y + inner.height)).toHaveLength(1)
      }
    }
  })

  it('start where an area starts, and keep to the frame', () => {
    const tiles = planTiles({ width: 1000, height: 1000 }, { x: 123, y: 900, width: 2000, height: 50 }, 512, 40)
    expect(tiles.map((tile) => tile.inner)).toEqual([
      { x: 123, y: 900, width: 389, height: 50 },
      { x: 512, y: 900, width: 488, height: 50 }
    ])
    expect(tiles[0].padded).toEqual({ x: 0, y: 768, width: 552, height: 222 })
  })

  it('fit the GPU with their border, however wide the blurs reach', () => {
    expect(tileSide(16384, 0)).toBe(2048)
    expect(tileSide(8192, 3000)).toBe(1536)
    expect(tileSide(4096, 3000)).toBe(TILE_ALIGN)
    expect(tileSide(16384, 0, 512)).toBe(512)
  })

  it('pad by how far the shown blurs reach, at the frame scale', () => {
    const blur = { ...adjustmentLayer('Gaussian Blur', 4000, 3000), adjustment: { ...defaultAdjustment('Gaussian Blur'), blurRadius: 40 } }
    const motion = { ...adjustmentLayer('Motion Blur', 4000, 3000), adjustment: { ...defaultAdjustment('Motion Blur'), motionDistance: 200 } }
    const curves = adjustmentLayer('Curves', 4000, 3000)
    expect(filterReach(doc([curves]), 1)).toBe(0)
    const both = filterReach(doc([blur, motion]), 1)
    expect(both).toBeGreaterThanOrEqual(120 + 100)
    expect(filterReach(doc([blur, motion]), 0.5)).toBeLessThan(both)
    const hidden = folderLayer('Off', 4000, 3000)
    expect(filterReach(doc([{ ...hidden, isVisible: false }, { ...blur, parentID: hidden.id }]), 1)).toBe(0)
  })

  it('size frames and bands', () => {
    expect(frameSize(12000, 9000, 0.5)).toEqual({ width: 6000, height: 4500 })
    expect(frameSize(3, 3, 0.01)).toEqual({ width: 1, height: 1 })
    expect(strips(1000, 300)).toEqual([
      { y: 0, height: 300 },
      { y: 300, height: 300 },
      { y: 600, height: 300 },
      { y: 900, height: 100 }
    ])
  })
})

describe('the view’s frame', () => {
  const viewport = { width: 1000, height: 700 }

  it('composites a document that fits whole, at the screen’s resolution', () => {
    const plan = planFrame(3000, 2000, { zoom: 0.25, panX: 125, panY: 100 }, viewport, 2, { maxTexture: 16384 })!
    expect(plan.scale).toBe(0.5)
    expect(plan.area).toEqual({ x: 0, y: 0, width: 1500, height: 1000 })
  })

  it('composites only what is in view of a large one, with room to pan, never past full size', () => {
    const plan = planFrame(12000, 9000, { zoom: 2, panX: -10000, panY: -8000 }, viewport, 2, { maxTexture: 16384, reach: () => 100 })!
    expect(plan.scale).toBe(1)
    expect(plan.needed).toEqual({ x: 5000, y: 4000, width: 500, height: 350 })
    expect(plan.area.x % TILE_ALIGN).toBe(0)
    expect(plan.area.x).toBeLessThanOrEqual(5000 - 100)
    expect(plan.area.x + plan.area.width).toBeGreaterThanOrEqual(5500 + 100)
    expect(covers(plan.area, plan.needed, 100, { width: 12000, height: 9000 })).toBe(true)
    // Panned past the room it left, it needs a new composite.
    expect(covers(plan.area, { ...plan.needed, x: plan.needed.x + 900 }, 100, { width: 12000, height: 9000 })).toBe(false)
  })

  it('halves the resolution for a draft, and draws nothing out of view', () => {
    expect(planFrame(4000, 3000, { zoom: 0.2, panX: 0, panY: 0 }, viewport, 2, { maxTexture: 8192, draft: true })!.scale).toBeCloseTo(0.2)
    expect(planFrame(4000, 3000, { zoom: 0.2, panX: 5000, panY: 0 }, viewport, 2, { maxTexture: 8192 })).toBeNull()
  })
})

describe('software renderers', () => {
  it('are told apart from graphics chips by their names', () => {
    expect(isSoftwareRenderer('ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 10.0.0) (0x0000C0DE)), SwiftShader driver)')).toBe(true)
    expect(isSoftwareRenderer('ANGLE (Mesa, llvmpipe (LLVM 22.1.8 128 bits), OpenGL ES 3.2 Mesa 26.2.3)')).toBe(true)
    expect(isSoftwareRenderer('softpipe')).toBe(true)
    expect(isSoftwareRenderer('ANGLE (Apple, ANGLE Metal Renderer: Apple M5 Max, Unspecified Version)')).toBe(false)
    expect(isSoftwareRenderer('ANGLE (Intel, Mesa Intel(R) Graphics (ADL GT2), OpenGL 4.6)')).toBe(false)
  })
})
