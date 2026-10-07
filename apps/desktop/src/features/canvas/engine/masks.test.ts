import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../../shared/canvas/comp-format.ts'
import { adjustmentLayer, type CanvasLayer, type DocState, findLayer, folderLayer, pixelLayer } from './document.ts'
import { maskFromSelection, maskOverPixels, withMaskAction } from './masks.ts'
import { Raster } from './raster.ts'

const W = 20
const H = 10

const stateOf = (layers: CanvasLayer[], selection: Raster | null = null): DocState => ({ width: W, height: H, resolution: 72, layers, activeLayerId: layers.at(-1)?.id ?? null, guides: [], selection })

/** A selection of the canvas's left half. */
function leftHalf(): Raster {
  const selection = new Raster(W, H, 1)

  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W / 2; x++) {
      selection.data[y * W + x] = 255
    }
  }

  return selection
}

const row = (raster: Raster, y = 0) => Array.from(raster.data.slice(y * raster.width, (y + 1) * raster.width))

describe('mask actions', () => {
  it('reveals or hides everything with a uniform mask', () => {
    const layer = pixelLayer('Photo', Raster.filled(W, H, [10, 20, 30, 255]))
    const shown = findLayer(withMaskAction(stateOf([layer]), layer.id, 'reveal'), layer.id)!
    expect(shown.mask?.width).toBe(1)
    expect(shown.mask?.data[0]).toBe(255)
    expect(findLayer(withMaskAction(stateOf([layer]), layer.id, 'hide'), layer.id)!.mask?.data[0]).toBe(0)
  })

  it('makes a mask from the selection on the layer’s own grid', () => {
    // An 8×4 layer at (6, 3): its left four pixels are in the selected half.
    const layer = pixelLayer('Logo', Raster.filled(8, 4, [255, 0, 0, 255]), defaultTransform(8, 4, 6, 3))
    const shown = findLayer(withMaskAction(stateOf([layer], leftHalf()), layer.id, 'revealSelection'), layer.id)!
    expect([shown.mask?.width, shown.mask?.height]).toEqual([8, 4])
    expect(row(shown.mask!)).toEqual([255, 255, 255, 255, 0, 0, 0, 0])
    const hidden = findLayer(withMaskAction(stateOf([layer], leftHalf()), layer.id, 'hideSelection'), layer.id)!
    expect(row(hidden.mask!)).toEqual([0, 0, 0, 0, 255, 255, 255, 255])
    expect(() => withMaskAction(stateOf([layer]), layer.id, 'revealSelection')).toThrow(/Nothing is selected/)
  })

  it('maps the selection through a scaled layer', () => {
    // 10×5 pixels drawn twice as big over the whole canvas.
    const layer = pixelLayer('Big', Raster.filled(10, 5, [0, 0, 0, 255]), defaultTransform(W, H, 0, 0))
    expect(row(maskFromSelection(layer, leftHalf(), false))).toEqual([255, 255, 255, 255, 255, 0, 0, 0, 0, 0])
  })

  it('gives folders and adjustments a mask the size of their box', () => {
    const folder = folderLayer('Folder', W, H)
    const masked = findLayer(withMaskAction(stateOf([folder], leftHalf()), folder.id, 'revealSelection'), folder.id)!
    expect([masked.mask?.width, masked.mask?.height]).toEqual([W, H])
    const adjustment = adjustmentLayer('Invert', W, H)
    expect(row(findLayer(withMaskAction(stateOf([adjustment], leftHalf()), adjustment.id, 'hideSelection'), adjustment.id)!.mask!)).toEqual([...Array(10).fill(0), ...Array(10).fill(255)])
  })

  it('inverts, switches off and removes', () => {
    const layer = { ...pixelLayer('Photo', Raster.filled(4, 1, [0, 0, 0, 255])), mask: new Raster(4, 1, 1, new Uint8ClampedArray([0, 100, 200, 255])), maskEnabled: true }
    const inverted = findLayer(withMaskAction(stateOf([layer]), layer.id, 'invert'), layer.id)!
    expect(row(inverted.mask!)).toEqual([255, 155, 55, 0])
    // The old raster stays as it was, for undo.
    expect(row(layer.mask)).toEqual([0, 100, 200, 255])
    expect(findLayer(withMaskAction(stateOf([layer]), layer.id, 'disable'), layer.id)!.maskEnabled).toBe(false)
    expect(findLayer(withMaskAction(stateOf([layer]), layer.id, 'remove'), layer.id)!.mask).toBeNull()
    const bare = pixelLayer('Bare', Raster.filled(2, 2, [0, 0, 0, 255]))
    expect(() => withMaskAction(stateOf([bare]), bare.id, 'invert')).toThrow(/has no mask/)
  })

  it('bakes the mask into the pixels and drops text and shape details', () => {
    const layer = {
      ...pixelLayer('Card', Raster.filled(4, 1, [200, 100, 50, 255])),
      mask: new Raster(4, 1, 1, new Uint8ClampedArray([0, 64, 128, 255])),
      maskEnabled: true,
      shape: { kind: 'Rectangle' as const, cornerRadius: 0, red: 1, green: 0, blue: 0 }
    }
    const applied = findLayer(withMaskAction(stateOf([layer]), layer.id, 'apply'), layer.id)!
    expect([0, 1, 2, 3].map((i) => applied.pixels!.data[i * 4 + 3])).toEqual([0, 64, 128, 255])
    expect(applied.pixels!.data[0]).toBe(200)
    expect(applied.mask).toBeNull()
    expect(applied.shape).toBeUndefined()
    expect(layer.pixels?.data[3]).toBe(255)
    const folder = { ...folderLayer('Folder', W, H), mask: Raster.filled(1, 1, 255, 1) }
    expect(() => withMaskAction(stateOf([folder]), folder.id, 'apply')).toThrow(/no pixels/)
  })

  it('unlinks a mask where the layer is, and relinks it resampled after a move', () => {
    const mask = new Raster(4, 1, 1, new Uint8ClampedArray([255, 255, 0, 0]))
    const layer = { ...pixelLayer('Photo', Raster.filled(4, 1, [0, 0, 0, 255]), defaultTransform(4, 1, 0, 0)), mask, maskEnabled: true }
    let state = withMaskAction(stateOf([layer]), layer.id, 'unlink')
    let current = findLayer(state, layer.id)!
    expect(current.maskLinked).toBe(false)
    expect(current.maskPlacement?.origin).toEqual([0, 0])
    // Unmoved, it relinks as it was.
    expect(findLayer(withMaskAction(state, layer.id, 'link'), layer.id)!.mask).toBe(mask)
    // Moved two pixels left, the mask stays behind: its shown half now falls on the layer's last two pixels.
    state = { ...state, layers: state.layers.map((entry) => (entry.id === layer.id ? { ...entry, transform: defaultTransform(4, 1, -2, 0) } : entry)) }
    current = findLayer(withMaskAction(state, layer.id, 'link'), layer.id)!
    expect(current.maskLinked).toBe(true)
    expect(current.maskPlacement).toBeUndefined()
    expect(row(current.mask!)).toEqual([0, 0, 255, 255])
    expect(row(maskOverPixels(findLayer(state, layer.id)!)!)).toEqual([0, 0, 255, 255])
  })
})
