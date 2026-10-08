import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  CompFormatError,
  defaultAdjustment,
  defaultHeraldAdjustment,
  defaultTransform,
  FORMAT_ID,
  FORMAT_VERSION,
  HERALD_ADJUSTMENT_KINDS,
  HERALD_RANGES,
  imageFileFor,
  type LayerRecord,
  maskFileFor,
  newId,
  newManifest,
  orderLayers,
  parseManifest,
  parseManifestText,
  RANGES,
  type RangeName,
  referencedAssets,
  serializeManifest,
  tableFileFor
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

describe("Compositor's ranges", () => {
  const adjustmentLayer = (adjustment: Record<string, unknown>) => manifest([{ ...layer(A), imageFile: undefined, adjustment }])
  const effectsLayer = (effects: Record<string, unknown>) => manifest([layer(A, { effects: effects as never })])
  const text = { content: 'Hello', fontName: 'Helvetica', fontSize: 40, red: 0, green: 0, blue: 0, alignment: 'Left', tracking: 0, leading: 0 }
  const textLayer = (style: Record<string, unknown>) => manifest([layer(A, { text: { ...text, ...style } as never })])
  const levels = (range: Record<string, number>) => {
    const ranges = defaultAdjustment('Levels').levels.ranges.map((entry, i) => (i === 1 ? { ...entry, ...range } : entry))

    return adjustmentLayer({ ...defaultAdjustment('Levels'), levels: { channel: 'RGB', ranges } })
  }
  const curve = (points: { x: number; y: number }[]) => adjustmentLayer({ ...defaultAdjustment('Curves'), curves: { channel: 'RGB', channels: [points, ...defaultAdjustment('Curves').curves.channels.slice(1)] } })

  // Each value at the edge of its range reads; just past it, the project is refused with the field and the range named.
  const cases: [string, (value: number) => unknown, number, number, RegExp][] = [
    ['exposure offset', (offset) => adjustmentLayer({ ...defaultAdjustment('Exposure'), exposureSettings: { exposure: 0, offset, gamma: 1 } }), 0.5, 0.51, /exposureSettings\.offset must be a number from -0\.5 to 0\.5 \(it was 0\.51\)/],
    ['exposure gamma', (gamma) => adjustmentLayer({ ...defaultAdjustment('Exposure'), exposureSettings: { exposure: 0, offset: 0, gamma } }), 9.99, 10, /exposureSettings\.gamma must be a number from 0\.01 to 9\.99/],
    ['grain size (small)', (size) => adjustmentLayer({ ...defaultAdjustment('Grain'), grainSettings: { amount: 25, size, roughness: 50, seed: 0 } }), 0.5, 0.4, /grainSettings\.size must be a number from 0\.5 to 20/],
    ['grain size (large)', (size) => adjustmentLayer({ ...defaultAdjustment('Grain'), grainSettings: { amount: 25, size, roughness: 50, seed: 0 } }), 20, 21, /grainSettings\.size must be a number from 0\.5 to 20/],
    ['levels black', (black) => levels({ black }), 254, 254.5, /ranges\[1\]\.black must be a number from 0 to 254/],
    ['levels gamma', (gamma) => levels({ gamma }), 0.1, 0.09, /ranges\[1\]\.gamma must be a number from 0\.1 to 9\.99/],
    ['levels white above black', (white) => levels({ black: 100, white }), 101, 100, /ranges\[1\]\.white \(100\) must be above .*black \(100\)/],
    ['hue', (hue) => adjustmentLayer({ ...defaultAdjustment('Hue/Saturation'), hue }), -360, -361, /adjustment\.hue must be a number from -360 to 360/],
    ['black and white weight', (reds) => adjustmentLayer({ ...defaultAdjustment('Black & White'), blackWhiteSettings: { ...defaultAdjustment('Black & White').blackWhiteSettings, reds } }), 300, 301, /blackWhiteSettings\.reds must be a number from -200 to 300/],
    ['motion angle', (motionAngle) => adjustmentLayer({ ...defaultAdjustment('Motion Blur'), motionAngle }), 90, 91, /motionAngle must be a number from -90 to 90/],
    ['noise amount', (noiseAmount) => adjustmentLayer({ ...defaultAdjustment('Add Noise'), noiseAmount }), 0.1, 0, /noiseAmount must be a number from 0\.1 to 400/],
    ['shadow distance', (distance) => effectsLayer({ shadow: { angle: 90, distance, blur: 20, red: 0, green: 0, blue: 0, opacity: 0.5 } }), 5000, 5001, /effects\.shadow\.distance must be a number from 0 to 5000/],
    ['inner shadow blur', (blur) => effectsLayer({ innerShadow: { angle: 90, distance: 10, blur, red: 0, green: 0, blue: 0, opacity: 0.5 } }), 500, 501, /effects\.innerShadow\.blur must be a number from 0 to 500/],
    ['stroke size', (size) => effectsLayer({ stroke: { size, red: 0, green: 0, blue: 0, opacity: 1, inside: false } }), 500, 501, /effects\.stroke\.size must be a number from 0 to 500/],
    ['glow size', (size) => effectsLayer({ outerGlow: { size, red: 1, green: 1, blue: 1, opacity: 0.75 } }), 500, 500.5, /effects\.outerGlow\.size must be a number from 0 to 500/],
    ['effect colour', (red) => effectsLayer({ colorOverlay: { red, green: 0, blue: 0, opacity: 1 } }), 1, 1.01, /effects\.colorOverlay\.red must be a number from 0 to 1/],
    ['font size', (fontSize) => textLayer({ fontSize }), 2000, 2001, /text\.fontSize must be a number from 1 to 2000/],
    ['tracking', (tracking) => textLayer({ tracking }), -100, -101, /text\.tracking must be a number from -100 to 1000/],
    ['leading', (leading) => textLayer({ leading }), 0, -1, /text\.leading must be a number from 0 to 5000/],
    ['paragraph box', (side) => textLayer({ boxSize: [side, 100] }), 16, 15, /text\.boxSize\[0\] must be a number from 16 to 30000/],
    ['layer size', (side) => manifest([layer(A, { transform: defaultTransform(side, 50) })]), 1, 0.5, /transform\.size\[0\] must be a number from 1 to 300000/]
  ]

  it.each(cases)('holds %s to its range', (_label, build, inside, outside, message) => {
    expect(() => parseManifest(build(inside))).not.toThrow()
    expect(() => parseManifest(build(outside))).toThrow(message)
  })

  it('holds curves to 2 to 32 points from x 0 to x 255', () => {
    const points = (count: number) => Array.from({ length: count }, (_, i) => ({ x: Math.round((i * 255) / (count - 1)), y: 128 }))
    expect(() => parseManifest(curve(points(32)))).not.toThrow()
    expect(() => parseManifest(curve(points(33)))).toThrow(/needs 2 to 32 points/)
    expect(() => parseManifest(curve([{ x: 4, y: 0 }, { x: 255, y: 255 }]))).toThrow(/must start at x 0 and end at x 255/)
    expect(() => parseManifest(curve([{ x: 0, y: 0 }, { x: 250, y: 255 }]))).toThrow(/must start at x 0 and end at x 255/)
  })

  it("holds Compositor's own Hue/Saturation ranges to the same bounds", () => {
    const hsv = (hue: number) => adjustmentLayer({ ...defaultAdjustment('Hue/Saturation'), hsvSettings: { range: 'Master', colorize: false, invertRange: false, adjustments: ['Master', { hue, saturation: 0, lightness: 0 }], bands: [] } })
    expect(() => parseManifest(hsv(180))).not.toThrow()
    expect(() => parseManifest(hsv(400))).toThrow(/hsvSettings\.adjustments\[0\]\.hue must be a number from -360 to 360/)
  })

  it('refuses clipping a folder, or clipping to an adjustment layer', () => {
    const adjustment = { ...layer(B), imageFile: undefined, adjustment: defaultAdjustment('Invert') }
    expect(() => parseManifest(manifest([adjustment, layer(A, { maskSourceID: B })]))).toThrow(/cannot clip it/)
    expect(() => parseManifest(manifest([layer(A), { ...layer(G), isGroup: true, imageFile: undefined, maskSourceID: A }]))).toThrow(/a folder cannot be clipped/)
  })

  it('names blank layers, drops empty letter runs and refuses guides that share an id', () => {
    const parsed = parseManifest(manifest([layer(A, { name: '   ', text: { ...text, colorRuns: [] } as never })]))
    expect(parsed.layers[0].name).toBe('Layer')
    expect(parsed.layers[0].text).not.toHaveProperty('colorRuns')
    const guide = { id: G, axis: 'vertical', position: 10 }
    expect(() => parseManifest(manifest([], { guides: [guide, guide] }))).toThrow(/Two guides share/)
  })

  it('reads values at the edges of every range, as Compositor writes them', () => {
    const exposure = { ...defaultAdjustment('Exposure'), exposureSettings: { exposure: -20, offset: -0.5, gamma: 0.01 } }
    const grain = { ...defaultAdjustment('Grain'), grainSettings: { amount: 100, size: 20, roughness: 0, seed: 4_294_967_295 } }
    const parsed = parseManifest(
      manifest([
        { ...layer(A), imageFile: undefined, adjustment: exposure },
        { ...layer(B), imageFile: undefined, adjustment: grain },
        layer(G, { text: { ...text, fontSize: 1, tracking: 1000, leading: 5000, boxSize: [16, 30_000] } as never, effects: { shadow: { angle: -360, distance: 5000, blur: 500, red: 1, green: 1, blue: 1, opacity: 0 } } })
      ])
    )
    expect(parsed.layers.map((entry) => entry.id)).toEqual([A, B, G])
  })

  it('lists the same ranges in the herald-canvas skill', () => {
    const skill = readFileSync(fileURLToPath(new URL('../../../../plugins/herald-os-bridge/skills/herald-canvas/SKILL.md', import.meta.url)), 'utf8').replace(/\s+/g, ' ')
    const shown = (name: RangeName) => RANGES[name].map((value) => String(value).replace('-', '−')).join('…')
    const listed: [string, RangeName][] = [
      ['`hue`', 'hue'],
      ['`saturation`', 'saturation'],
      ['`lightness`', 'lightness'],
      ['`black`', 'levelsBlack'],
      ['`gamma`', 'levelsGamma'],
      ['`white`', 'levelsWhite'],
      ['`outputBlack`', 'levelsOutput'],
      ['`exposureSettings.exposure`', 'exposure'],
      ['`offset`', 'exposureOffset'],
      ['`gamma`', 'exposureGamma'],
      ['`grainSettings.amount`', 'grainAmount'],
      ['`size`', 'grainSize'],
      ['`roughness`', 'grainRoughness'],
      ['`magentas`', 'blackWhite'],
      ['`tintHue`', 'tintHue'],
      ['`tintSaturation`', 'tintSaturation'],
      ['each', 'colorBalance'],
      ['`blurRadius`', 'blurRadius'],
      ['`motionAngle`', 'motionAngle'],
      ['`motionDistance`', 'motionDistance'],
      ['`noiseAmount`', 'noiseAmount'],
      ['`angle`', 'shadowAngle'],
      ['`distance`', 'shadowDistance'],
      ['`blur`', 'shadowBlur'],
      ['`size`', 'glowSize'],
      ['`size`', 'strokeSize']
    ]

    for (const [field, name] of listed) {
      expect(skill, `${field} ${name}`).toContain(`${field} ${shown(name)}`)
    }

    expect(skill).toContain(`of ${shown('curvePoints')}`)

    for (const name of ['fontSize', 'tracking', 'leading', 'textBox', 'layerSize'] as const) {
      expect(skill, name).toContain(shown(name))
    }

    // Herald's own adjustments, held to Herald's bounds.
    const herald = (name: keyof typeof HERALD_RANGES) => HERALD_RANGES[name].map((value) => String(value).replace('-', '−')).join('…')
    const heraldListed: [string, keyof typeof HERALD_RANGES][] = [
      ['`brightness`', 'brightness'],
      ['`contrast`', 'contrast'],
      ['`vibrance`', 'vibrance'],
      ['`saturation`', 'saturation'],
      ['`density`', 'density'],
      ['`constant`', 'mixer'],
      ['`black`', 'inks'],
      ['`levels`', 'posterize'],
      ['`level`', 'threshold']
    ]

    for (const [field, name] of heraldListed) {
      expect(skill, `${field} ${name}`).toContain(`${field} ${herald(name)}`)
    }

    expect(skill).toContain(`${herald('tableSize')} entries a side`)
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

describe("Herald's own adjustments", () => {
  const adjustmentLayer = (herald: Record<string, unknown>) => ({ ...layer(A), imageFile: undefined, adjustment: defaultAdjustment('Levels'), heraldAdjustment: herald })

  it('round-trips every kind with its defaults filled in, beside a stand-in Compositor reads', () => {
    for (const kind of HERALD_ADJUSTMENT_KINDS) {
      const base = newManifest(100, 50)
      base.layers = [adjustmentLayer({ kind }) as LayerRecord]
      const written = JSON.parse(serializeManifest(base))
      expect(written.layers[0].heraldAdjustment, kind).toEqual(defaultHeraldAdjustment(kind))
      // What Compositor decodes is untouched: its own kind, complete.
      expect(written.layers[0].adjustment.kind).toBe('Levels')
      expect(parseManifestText(JSON.stringify(written)).layers[0].heraldAdjustment).toEqual(defaultHeraldAdjustment(kind))
    }
  })

  it('keeps settings and fields it does not know, and a kind from a newer version as it was', () => {
    const parsed = parseManifest(manifest([adjustmentLayer({ kind: 'Vibrance', vibrance: 35, note: 'kept' })]))
    expect(parsed.layers[0].heraldAdjustment).toEqual({ kind: 'Vibrance', vibrance: 35, saturation: 0, note: 'kept' })
    const future = { kind: 'Shadows/Highlights', amount: 12, nested: { a: [1, 2] } }
    expect(parseManifest(manifest([adjustmentLayer(future)])).layers[0].heraldAdjustment).toEqual(future)
  })

  it('holds the settings to their bounds and needs an adjustment beside them', () => {
    const cases: [string, unknown][] = [
      ['brightness past 150', manifest([adjustmentLayer({ kind: 'Brightness/Contrast', brightness: 151 })])],
      ['two posterize levels and a half', manifest([adjustmentLayer({ kind: 'Posterize', levels: 2.5 })])],
      ['a mixer share past 200%', manifest([adjustmentLayer({ kind: 'Channel Mixer', red: { red: 250 } })])],
      ['an ink past 100%', manifest([adjustmentLayer({ kind: 'Selective Color', reds: { cyan: -101 } })])],
      ['a one-entry table', manifest([adjustmentLayer({ kind: 'Color Lookup', size: 1 })])],
      ['no kind', manifest([adjustmentLayer({ vibrance: 1 })])],
      ['settings on a picture layer', manifest([layer(A, { heraldAdjustment: { kind: 'Threshold', level: 9 } })])]
    ]

    for (const [label, value] of cases) {
      expect(() => parseManifest(value), label).toThrow(CompFormatError)
    }
  })

  it('names a Color Lookup layer’s table among the project’s files once it has one', () => {
    const base = newManifest(100, 50)
    base.layers = [adjustmentLayer({ kind: 'Color Lookup', name: 'Film.cube', size: 33 }) as LayerRecord]
    expect([...referencedAssets(base)]).toEqual([tableFileFor(A)])
    base.layers = [adjustmentLayer({ kind: 'Color Lookup', size: 0 }) as LayerRecord]
    expect([...referencedAssets(base)]).toEqual([])
  })
})

describe('orderLayers', () => {
  it('puts each folder right before its children, keeping sibling order', () => {
    const folder = { ...layer(G), isGroup: true, imageFile: undefined }
    const ordered = orderLayers([layer(A, { parentID: G }), layer(B), folder])
    expect(ordered.map(l => l.id)).toEqual([B, G, A])
  })
})
