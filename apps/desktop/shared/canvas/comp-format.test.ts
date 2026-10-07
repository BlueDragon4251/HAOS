import { describe, expect, it } from 'vitest'
import {
  CompFormatError,
  defaultAdjustment,
  defaultTransform,
  FORMAT_ID,
  FORMAT_VERSION,
  imageFileFor,
  type LayerRecord,
  maskFileFor,
  newId,
  newManifest,
  orderLayers,
  parseManifest,
  parseManifestText,
  referencedAssets,
  serializeManifest
} from './comp-format.ts'

const A = '6F1D3C2A-0B7E-4E8A-9C4D-2A1B3C4D5E6F'
const B = 'A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D'
const G = '0C5E7A91-3B2D-4F6A-8E1C-9D0B7A6F5E4D'

const layer = (id: string, extra: Partial<LayerRecord> = {}): LayerRecord => ({ id, name: 'Layer', isVisible: true, transform: defaultTransform(100, 50), imageFile: imageFileFor(id), ...extra })

const manifest = (layers: unknown[], extra: Record<string, unknown> = {}) => ({ format: FORMAT_ID, version: 11, documentID: newId(), width: 100, height: 50, layers, ...extra })

describe('parseManifest', () => {
  it('reads a minimal project and fills in the defaults', () => {
    const parsed = parseManifest(manifest([{ id: A.toLowerCase(), name: 'Background', isVisible: true, transform: { origin: [0, 0], size: [100, 50] }, imageFile: imageFileFor(A) }]))
    expect(parsed.resolution).toBe(72)
    expect(parsed.colorSpace).toBe('sRGB')
    expect(parsed.layers[0]).toMatchObject({ id: A, opacity: 1, blendMode: 'Normal', isGroup: false, transform: { rotation: 0, flipX: false, sampling: 'High quality' } })
    expect(parsed.activeLayerID).toBeNull()
  })

  it('refuses what a strict reader refuses', () => {
    const cases: [string, unknown][] = [
      ['another format', { ...manifest([]), format: 'com.example' }],
      ['a newer version', { ...manifest([]), version: FORMAT_VERSION + 1 }],
      ['an image named for another layer', manifest([layer(A, { imageFile: imageFileFor(B) })])],
      ['a lowercase image name', manifest([layer(A, { imageFile: `${A.toLowerCase()}.png` })])],
      ['two layers with one id', manifest([layer(A), layer(A)])],
      ['a folder with pixels', manifest([layer(A, { isGroup: true })])],
      ['a parent that is not a folder', manifest([layer(A), layer(B, { parentID: A })])],
      ['a missing parent', manifest([layer(B, { parentID: G })])],
      ['an unknown blend mode', manifest([layer(A, { blendMode: 'Dissolve' as never })])],
      ['opacity above 1', manifest([layer(A, { opacity: 1.5 })])],
      ['clipping to a folder', manifest([{ ...layer(G), isGroup: true, imageFile: undefined }, layer(A, { maskSourceID: G })])],
      ['clipping in a loop', manifest([layer(A, { maskSourceID: B }), layer(B, { maskSourceID: A })])],
      ['a canvas too wide', { ...manifest([]), width: 40_000 }],
      ['curves out of order', manifest([{ ...layer(A), imageFile: undefined, adjustment: { ...defaultAdjustment('Curves'), curves: { channel: 'RGB', channels: [[{ x: 10, y: 0 }, { x: 5, y: 9 }], [], [], []] } } }])]
    ]

    for (const [label, value] of cases) {
      expect(() => parseManifest(value), label).toThrow(CompFormatError)
    }
  })

  it('keeps folders as pass-through: their blend mode stays Normal', () => {
    const parsed = parseManifest(manifest([{ id: G, name: 'Folder', isVisible: true, isGroup: true, blendMode: 'Multiply', opacity: 0.5, transform: defaultTransform(100, 50) }, layer(A, { parentID: G })]))
    expect(parsed.layers[0]).toMatchObject({ isGroup: true, blendMode: 'Normal', opacity: 0.5 })
  })

  it('keeps fields it does not know, at every level', () => {
    const adjustment = { ...defaultAdjustment('Hue/Saturation'), hsvSettings: { range: 'Reds', colorize: false } }
    const parsed = parseManifest(manifest([{ ...layer(A), imageFile: undefined, adjustment, futureField: 7 }], { camera: { lens: 35 } }))
    expect(parsed.camera).toEqual({ lens: 35 })
    expect(parsed.layers[0].futureField).toBe(7)
    expect(parsed.layers[0].adjustment?.hsvSettings).toEqual({ range: 'Reds', colorize: false })
  })

  it('accepts masks named for their layer, enabled unless they say otherwise', () => {
    const parsed = parseManifest(manifest([layer(A, { maskFile: maskFileFor(A) })]))
    expect(parsed.layers[0].maskEnabled).toBe(true)
    expect(referencedAssets(parsed)).toEqual(new Set([imageFileFor(A), maskFileFor(A)]))
  })

  it('reads text runs only when they stay inside the text', () => {
    const text = { content: 'Hello', fontName: 'Helvetica', fontSize: 40, red: 0, green: 0, blue: 0, alignment: 'Left', tracking: 0, leading: 0 }
    expect(parseManifest(manifest([layer(A, { text: { ...text, colorRuns: [{ location: 1, length: 2, red: 1, green: 0, blue: 0 }] } as never })])).layers[0].text?.colorRuns).toHaveLength(1)
    expect(() => parseManifest(manifest([layer(A, { text: { ...text, colorRuns: [{ location: 4, length: 3, red: 1, green: 0, blue: 0 }] } as never })]))).toThrow(CompFormatError)
  })

  it('rejects text that is not JSON', () => {
    expect(() => parseManifestText('{ nope')).toThrow(CompFormatError)
  })
})

describe('serializeManifest', () => {
  it('writes the current version and complete records a strict reader can decode', () => {
    const base = newManifest(640, 480)
    base.layers = [{ ...layer(A), imageFile: undefined, adjustment: defaultAdjustment('Exposure') }]
    const written = JSON.parse(serializeManifest({ ...base, version: 3 }))
    expect(written.version).toBe(FORMAT_VERSION)
    expect(written.layers[0].adjustment).toMatchObject({ kind: 'Exposure', hue: 0, colorize: false, exposureSettings: { exposure: 0, offset: 0, gamma: 1 } })
    expect(written.layers[0].adjustment.levels.ranges).toHaveLength(4)
    expect(written.layers[0].adjustment.curves.channels).toHaveLength(4)
    expect(written.layers[0].transform).toEqual({ origin: [0, 0], size: [100, 50], rotation: 0, flipX: false, flipY: false, sampling: 'High quality' })
  })

  it('never writes a manifest that would not load again', () => {
    const broken = newManifest(10, 10)
    broken.layers = [layer(A), layer(A)]
    expect(() => serializeManifest(broken)).toThrow(CompFormatError)
  })
})

describe('orderLayers', () => {
  it('puts each folder right before its children, keeping sibling order', () => {
    const folder = { ...layer(G), isGroup: true, imageFile: undefined }
    const ordered = orderLayers([layer(A, { parentID: G }), layer(B), folder])
    expect(ordered.map(l => l.id)).toEqual([B, G, A])
  })
})
