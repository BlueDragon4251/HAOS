import { initializeCanvas, type Layer, type Psd, readPsd, writePsdUint8Array } from 'ag-psd'
import { beforeAll, describe, expect, it } from 'vitest'
import { defaultAdjustment, defaultEffect, defaultTransform, type LayerRecord, newId, parseManifest, serializeManifest, newManifest, imageFileFor, maskFileFor } from '../../../../shared/canvas/comp-format.ts'
import { adjustmentFrom, adjustmentTo, fromPsd, Notes, type PixelData, type PsdSourceLayer, rgbOf, toPsd } from './psd-map.ts'

beforeAll(() => {
  // The tests run without a canvas: ag-psd makes plain pixel buffers, as in the worker.
  initializeCanvas(
    () => {
      throw new Error('no canvas in tests')
    },
    (width, height) => ({ width, height, data: new Uint8ClampedArray(width * height * 4) }) as ImageData
  )
})

const solid = (width: number, height: number, rgba: number[]) => {
  const data = new Uint8ClampedArray(width * height * 4)

  for (let i = 0; i < width * height; i++) {
    data.set(rgba, i * 4)
  }

  return { width, height, data }
}

const ramp = (width: number, height: number) => {
  const data = new Uint8ClampedArray(width * height * 4)

  for (let i = 0; i < width * height; i++) {
    const v = Math.round(((i % width) / (width - 1)) * 255)
    data.set([v, v, v, 255], i * 4)
  }

  return { width, height, data }
}

/** A document written by ag-psd and read back the way the worker reads one. */
const roundTrip = (psd: Psd): Psd => readPsd(writePsdUint8Array(psd, { noBackground: true }).buffer as ArrayBuffer, { useImageData: true })

const px = (value: number) => ({ units: 'Pixels' as const, value })

function sample(): Psd {
  return {
    width: 200,
    height: 100,
    imageData: solid(200, 100, [255, 0, 0, 255]),
    imageResources: { resolutionInfo: { horizontalResolution: 300, horizontalResolutionUnit: 'PPI', widthUnit: 'Inches', verticalResolution: 300, verticalResolutionUnit: 'PPI', heightUnit: 'Inches' } },
    children: [
      { name: 'Background', left: 0, top: 0, right: 200, bottom: 100, imageData: solid(200, 100, [255, 0, 0, 255]) },
      { name: 'Multiply box', left: 20, top: 10, right: 70, bottom: 50, opacity: 0.5, blendMode: 'multiply', imageData: solid(50, 40, [0, 128, 255, 255]) },
      {
        name: 'Folder',
        opened: true,
        blendMode: 'pass through',
        opacity: 0.8,
        hidden: true,
        children: [
          { name: 'Inside', left: 100, top: 20, right: 130, bottom: 50, imageData: solid(30, 30, [0, 0, 255, 255]), mask: { left: 110, top: 20, right: 130, bottom: 50, defaultColor: 0, imageData: ramp(20, 30) } },
          { name: 'Clipped', left: 105, top: 25, right: 125, bottom: 45, clipping: true, imageData: solid(20, 20, [0, 255, 0, 255]) }
        ]
      },
      { name: 'Grain', left: 0, top: 0, right: 10, bottom: 10, blendMode: 'dissolve', imageData: solid(10, 10, [9, 9, 9, 255]) },
      { name: 'Multiply folder', opened: true, blendMode: 'multiply', children: [{ name: 'In it', left: 0, top: 0, right: 4, bottom: 4, imageData: solid(4, 4, [1, 2, 3, 255]) }] },
      {
        name: 'Title',
        left: 10,
        top: 60,
        right: 80,
        bottom: 90,
        imageData: solid(70, 30, [255, 255, 255, 255]),
        text: {
          text: 'Hello\rWorld',
          transform: [1, 0, 0, 1, 10, 80],
          style: { font: { name: 'ArialMT' }, fontSize: 24, fillColor: { r: 255, g: 255, b: 255 }, tracking: 50 },
          styleRuns: [
            { length: 5, style: { fillColor: { r: 255, g: 0, b: 0 } } },
            { length: 6, style: { font: { name: 'Arial-BoldMT' } } }
          ],
          paragraphStyle: { justification: 'center' }
        }
      },
      { name: 'Curves', adjustment: { type: 'curves', rgb: [{ input: 0, output: 0 }, { input: 128, output: 150 }, { input: 255, output: 255 }] } },
      { name: 'Levels', adjustment: { type: 'levels', rgb: { shadowInput: 10, highlightInput: 240, midtoneInput: 1.2, shadowOutput: 5, highlightOutput: 250 } } },
      { name: 'Tint', adjustment: { type: 'hue/saturation', master: { a: 256, b: 200, c: 40, d: -10, hue: 0, saturation: 0, lightness: 0 } } },
      { name: 'Threshold', adjustment: { type: 'threshold', level: 128 } },
      {
        name: 'Card',
        left: 120,
        top: 60,
        right: 170,
        bottom: 90,
        imageData: solid(50, 30, [255, 255, 0, 255]),
        effects: {
          dropShadow: [{ enabled: true, size: px(12), distance: px(8), angle: 120, color: { r: 0, g: 0, b: 0 }, opacity: 0.6, blendMode: 'multiply' }],
          stroke: [{ enabled: false, size: px(3), position: 'inside', fillType: 'color', color: { r: 255, g: 255, b: 255 }, opacity: 1, blendMode: 'normal' }],
          bevel: { enabled: true, size: px(5) }
        }
      }
    ]
  }
}

describe('Photoshop documents into Herald layers', () => {
  const imported = () => fromPsd(roundTrip(sample()))

  it('keeps the order, folders, visibility, opacity and blend modes', () => {
    const { layers, width, height, resolution } = imported()
    expect([width, height, resolution]).toEqual([200, 100, 300])
    expect(layers.map((layer) => layer.record.name)).toEqual(['Background', 'Multiply box', 'Folder', 'Inside', 'Clipped', 'Grain', 'Multiply folder', 'In it', 'Title', 'Curves', 'Levels', 'Tint', 'Card'])
    const byName = new Map(layers.map((layer) => [layer.record.name, layer.record]))
    expect(byName.get('Multiply box')).toMatchObject({ blendMode: 'Multiply', opacity: 0.5, transform: { origin: [20, 10], size: [50, 40] } })
    expect(byName.get('Folder')).toMatchObject({ isGroup: true, isVisible: false, blendMode: 'Normal' })
    expect(byName.get('Folder')!.opacity).toBeCloseTo(0.8, 2)
    expect(byName.get('Inside')!.parentID).toBe(byName.get('Folder')!.id)
    expect(byName.get('Grain')!.blendMode).toBe('Normal')
  })

  it('maps masks onto the layer’s box and clipping onto its base', () => {
    const { layers } = imported()
    const inside = layers.find((layer) => layer.record.name === 'Inside')!
    const clipped = layers.find((layer) => layer.record.name === 'Clipped')!
    expect(inside.record).toMatchObject({ maskEnabled: true, maskLinked: true })
    expect([inside.mask!.width, inside.mask!.height, inside.mask!.channels]).toEqual([30, 30, 1])
    // Left of the mask's own box lies outside it (hidden); the ramp starts at its left edge.
    expect(inside.mask!.data[0]).toBe(0)
    expect(inside.mask!.data[29]).toBe(255)
    expect(clipped.record.maskSourceID).toBe(inside.record.id)
  })

  it('keeps text editable, with its colour and font runs', () => {
    const title = imported().layers.find((layer) => layer.record.name === 'Title')!
    expect(title.record.text).toMatchObject({ content: 'Hello\nWorld', fontName: 'ArialMT', fontSize: 24, alignment: 'Center', red: 1, green: 0, blue: 0 })
    expect(title.record.text!.tracking).toBeCloseTo(1.2, 5)
    expect(title.record.text!.colorRuns).toEqual([{ location: 5, length: 6, red: 1, green: 1, blue: 1 }])
    expect(title.record.text!.fontRuns).toEqual([{ location: 5, length: 6, fontName: 'Arial-BoldMT' }])
    expect(title.textAnchor).toEqual([10, 80])
  })

  it('maps the adjustments Herald has, and notes the rest', () => {
    const { layers, notes } = imported()
    const adjustment = (name: string) => layers.find((layer) => layer.record.name === name)!.record.adjustment!
    expect(adjustment('Curves').curves.channels[0]).toEqual([
      { x: 0, y: 0 },
      { x: 128, y: 150 },
      { x: 255, y: 255 }
    ])
    expect(adjustment('Levels').levels.ranges[0]).toEqual({ black: 10, white: 240, gamma: 1.2, outputBlack: 5, outputWhite: 250 })
    expect(adjustment('Tint')).toMatchObject({ kind: 'Hue/Saturation', colorize: true, hue: 200, saturation: 40, lightness: -10 })
    expect(notes.some((note) => note.startsWith('Threshold adjustment layers have no counterpart'))).toBe(true)
    expect(notes.some((note) => note.includes('Blend mode Dissolve') && note.includes('“Grain”'))).toBe(true)
    expect(notes.some((note) => note.includes('(Multiply) became Pass Through') && note.includes('“Multiply folder”'))).toBe(true)
  })

  it('maps layer effects, hidden ones too, and notes the ones Herald does not draw', () => {
    const { layers, notes } = imported()
    const card = layers.find((layer) => layer.record.name === 'Card')!
    expect(card.record.effects!.shadow).toMatchObject({ angle: 120, distance: 8, blur: 12, red: 0, green: 0, blue: 0, opacity: 0.6 })
    expect(card.record.effects!.stroke).toMatchObject({ enabled: false, size: 3, inside: true, red: 1, green: 1, blue: 1 })
    expect(notes.some((note) => note.includes('bevel and emboss'))).toBe(true)
  })

  it('makes records the format accepts', () => {
    const { layers, width, height } = imported()
    const manifest = newManifest(width, height)
    manifest.layers = layers.map(({ record, pixels, mask }) => ({ ...record, ...(pixels ? { imageFile: imageFileFor(record.id) } : {}), ...(mask ? { maskFile: maskFileFor(record.id) } : {}) }))
    expect(() => parseManifest(JSON.parse(serializeManifest(manifest)))).not.toThrow()
  })

  it('reads every colour model as RGB', () => {
    expect(rgbOf({ r: 255, g: 0, b: 51 })).toEqual({ red: 1, green: 0, blue: 0.2 })
    expect(rgbOf({ fr: 0.5, fg: 0.25, fb: 1 })).toEqual({ red: 0.5, green: 0.25, blue: 1 })
    expect(rgbOf({ h: 1 / 3, s: 100, b: 100 })).toEqual({ red: 0, green: 1, blue: 0 })
    expect(rgbOf({ c: 0, m: 100, y: 100, k: 0 })).toEqual({ red: 1, green: 0, blue: 0 })
    expect(rgbOf({ k: 25 })).toEqual({ red: 0.75, green: 0.75, blue: 0.75 })
    const white = rgbOf({ l: 100, a: 0, b: 0 })
    expect(white.red).toBeCloseTo(1, 2)
  })

  it('lets go of what it cannot hold, with a note', () => {
    const notes = new Notes()
    expect(adjustmentFrom({ type: 'posterize', levels: 4 }, notes, 'Poster')).toBeNull()
    expect(notes.list()[0]).toMatch(/Posterize adjustment layers have no counterpart.*“Poster”/)
  })
})

const pixels = (width: number, height: number, rgba: number[]): PixelData => ({ ...solid(width, height, rgba), channels: 4 })

describe('Herald layers into Photoshop documents', () => {
  const record = (name: string, extra: Partial<LayerRecord> = {}): LayerRecord => ({ id: newId(), name, isVisible: true, transform: defaultTransform(10, 10), isGroup: false, opacity: 1, blendMode: 'Normal', ...extra })

  it('writes layers, folders, masks, clipping, text, adjustments and effects, and reads back the same', () => {
    const base = record('Photo', { transform: defaultTransform(40, 30, 5, 6) })
    const folder = record('Folder', { isGroup: true, opacity: 0.5, transform: defaultTransform(100, 80) })
    const inside = record('Inside', { parentID: folder.id, blendMode: 'Screen', isVisible: false, transform: defaultTransform(20, 20, 50, 40) })
    const clipped = record('Clipped', { maskSourceID: base.id, transform: defaultTransform(40, 30, 5, 6) })
    const text = record('Title', {
      transform: defaultTransform(60, 30, 10, 40),
      text: { content: 'Hi\nthere', fontName: 'HelveticaNeue-Bold', fontSize: 20, red: 1, green: 0, blue: 0, alignment: 'Right', tracking: 2, leading: 0, colorRuns: [{ location: 3, length: 5, red: 0, green: 0, blue: 1 }] }
    })
    const curves = record('Curves', { adjustment: { ...defaultAdjustment('Curves'), curves: { channel: 'RGB', channels: [[{ x: 0, y: 10 }, { x: 255, y: 240 }], [{ x: 0, y: 0 }, { x: 255, y: 255 }], [{ x: 0, y: 0 }, { x: 255, y: 255 }], [{ x: 0, y: 0 }, { x: 255, y: 255 }]] } } })
    const tint = record('Tint', { adjustment: { ...defaultAdjustment('Hue/Saturation'), colorize: true, hue: 30, saturation: 50, lightness: 0 } })
    const blur = record('Blur', { adjustment: defaultAdjustment('Gaussian Blur') })
    const card = record('Card', { transform: defaultTransform(20, 10, 70, 5), effects: { shadow: { ...defaultEffect.shadow(), distance: 7 }, stroke: { ...defaultEffect.stroke(), inside: true, enabled: false }, outerGlow: defaultEffect.outerGlow() } })
    const layers: PsdSourceLayer[] = [
      { record: base, pixels: { left: 5, top: 6, image: pixels(40, 30, [10, 20, 30, 255]) }, mask: null },
      { record: clipped, pixels: { left: 5, top: 6, image: pixels(40, 30, [200, 0, 0, 255]) }, mask: null },
      { record: folder, pixels: null, mask: { left: 0, top: 0, image: { width: 1, height: 1, channels: 1, data: new Uint8ClampedArray([255]) }, outside: 255 } },
      { record: inside, pixels: { left: 50, top: 40, image: pixels(20, 20, [0, 0, 255, 255]) }, mask: { left: 50, top: 40, image: { width: 20, height: 20, channels: 1, data: new Uint8ClampedArray(400).fill(128) }, outside: 0 } },
      { record: text, pixels: { left: 10, top: 40, image: pixels(60, 30, [255, 0, 0, 255]) }, mask: null, textTransform: [1, 0, 0, 1, 70, 61] },
      { record: curves, pixels: null, mask: null },
      { record: tint, pixels: null, mask: null },
      { record: blur, pixels: null, mask: null },
      { record: card, pixels: { left: 70, top: 5, image: pixels(20, 10, [255, 255, 255, 255]) }, mask: null }
    ]
    const { psd, notes } = toPsd({ width: 100, height: 80, resolution: 144, layers, composite: pixels(100, 80, [1, 2, 3, 255]) })
    expect(notes.some((note) => note.startsWith('Gaussian Blur has no adjustment layer in Photoshop'))).toBe(true)
    const back = roundTrip(psd)
    const names = (list: Layer[] | undefined): unknown[] => (list ?? []).map((layer) => (layer.children ? [layer.name, names(layer.children)] : layer.name))
    expect(names(back.children)).toEqual(['Photo', 'Clipped', ['Folder', ['Inside']], 'Title', 'Curves', 'Tint', 'Card'])
    const [photo, clip, group, title, curve, hue, fx] = back.children!
    expect([photo.left, photo.top, photo.right, photo.bottom]).toEqual([5, 6, 45, 36])
    expect(clip.clipping).toBe(true)
    expect(group).toMatchObject({ blendMode: 'pass through', opened: true })
    expect(group.opacity).toBeCloseTo(0.5, 2)
    expect(group.children![0]).toMatchObject({ blendMode: 'screen', hidden: true, mask: { left: 50, top: 40, right: 70, bottom: 60, defaultColor: 0 } })
    expect(title.text).toMatchObject({ text: 'Hi\nthere', transform: [1, 0, 0, 1, 70, 61], paragraphStyle: { justification: 'right' } })
    expect(title.text!.styleRuns!.map((run) => [run.length, run.style.fillColor])).toEqual([
      [3, { r: 255, g: 0, b: 0 }],
      [5, { r: 0, g: 0, b: 255 }]
    ])
    expect(curve.adjustment).toMatchObject({ type: 'curves', rgb: [{ input: 0, output: 10 }, { input: 255, output: 240 }] })
    expect(adjustmentFrom(hue.adjustment!, new Notes(), 'Tint')).toMatchObject({ colorize: true, hue: 30, saturation: 50 })
    expect(fx.effects!.dropShadow![0]).toMatchObject({ distance: { value: 7 }, angle: 90 })
    expect(fx.effects!.stroke![0]).toMatchObject({ enabled: false, position: 'inside' })
    expect(fx.effects!.outerGlow).toMatchObject({ size: { value: 20 } })
    expect(back.imageResources?.resolutionInfo?.horizontalResolution).toBe(144)
  })

  it('writes the adjustments Photoshop has the way it reads them again', () => {
    for (const kind of ['Hue/Saturation', 'Levels', 'Curves', 'Exposure', 'Invert', 'Black & White', 'Color Balance', 'Gradient Map'] as const) {
      const adjustment = defaultAdjustment(kind)
      const written = adjustmentTo(adjustment)!
      const read = adjustmentFrom(written, new Notes(), kind)!
      expect(read.kind).toBe(kind)
    }

    for (const kind of ['Grain', 'Gaussian Blur', 'Motion Blur', 'Add Noise'] as const) {
      expect(adjustmentTo(defaultAdjustment(kind))).toBeNull()
    }
  })
})
