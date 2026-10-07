import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../shared/canvas/comp-format.ts'
import {
  alignFrom,
  anchorFrom,
  blendFrom,
  cropBox,
  describeLayer,
  describeLayers,
  fillBox,
  findByRef,
  fontNameFrom,
  lineEnds,
  mergeSettings,
  opacityFrom,
  placementOf,
  resizePlan,
  resolvePath,
  shapeKindFrom
} from './agent-model.ts'
import { blankLayer, type DocState, folderLayer, insertLayer, pixelLayer, setClipped } from './engine/document.ts'
import { Raster } from './engine/raster.ts'
import { textStyle } from './engine/text.ts'

const build = () => {
  let state: DocState = { width: 1000, height: 800, resolution: 72, layers: [], activeLayerId: null, guides: [], selection: null }
  const photo = pixelLayer('Photo', new Raster(2000, 1000), defaultTransform(1000, 500, 0, 150))
  state = insertLayer(state, photo, {})
  const folder = folderLayer('Titles', 1000, 800)
  state = insertLayer(state, folder, {})
  state = insertLayer(state, { ...blankLayer('Headline', 1000, 800), opacity: 0.5 }, { parentID: folder.id })
  const tint = { ...blankLayer('Tint', 1000, 800), blendMode: 'Multiply' as const }
  state = insertLayer(state, tint, { above: photo.id })
  state = setClipped(state, tint.id, true)

  return { state, photo, folder, tint }
}

describe('resolvePath', () => {
  it('expands the home folder and tidies the path', () => {
    expect(resolvePath('~/Pictures//Poster.comp/', '/home/luke')).toBe('/home/luke/Pictures/Poster.comp')
    expect(resolvePath('/tmp/./a', '')).toBe('/tmp/a')
  })

  it('refuses relative paths', () => {
    expect(() => resolvePath('Pictures/a.png', '/home/luke')).toThrow(/full path/)
  })
})

describe('findByRef', () => {
  it('finds by id, by name (the topmost), or by a unique part of a name', () => {
    const { state, photo } = build()
    expect(findByRef(state, photo.id.toLowerCase()).name).toBe('Photo')
    expect(findByRef(state, 'headline').name).toBe('Headline')
    expect(findByRef(state, 'tit').name).toBe('Titles')
  })

  it('names the layers when nothing matches', () => {
    const { state } = build()
    expect(() => findByRef(state, 'Logo')).toThrow(/Photo, Tint, Titles, Headline/)
    expect(() => findByRef(state, 'e')).toThrow(/Several layers match/)
  })
})

describe('describeLayers', () => {
  it('lists top to bottom with folders, clipping and appearance', () => {
    const { state } = build()
    const rows = describeLayers(state)
    expect(rows.map((row) => row.name)).toEqual(['Titles', 'Headline', 'Tint', 'Photo'])
    expect(rows[0]).toMatchObject({ kind: 'folder', blend: 'Pass Through' })
    expect(rows[1]).toMatchObject({ folder: 'Titles', opacity: 0.5 })
    expect(rows[2]).toMatchObject({ clippedTo: 'Photo', blend: 'Multiply', kind: 'blank' })
    expect(rows[3]).toMatchObject({ kind: 'pixels', pixels: '2000×1000', x: 0, y: 150, width: 1000, height: 500 })
  })
})

describe('placementOf', () => {
  const canvas = { width: 1000, height: 800 }

  it('fits inside the canvas without enlarging, centred', () => {
    expect(placementOf(2000, 1000, canvas, {})).toEqual({ x: 0, y: 150, width: 1000, height: 500 })
    expect(placementOf(100, 50, canvas, {})).toEqual({ x: 450, y: 375, width: 100, height: 50 })
  })

  it('covers, keeps its size, or takes a box with one side', () => {
    expect(placementOf(500, 500, canvas, { fit: 'cover' })).toEqual({ x: 0, y: -100, width: 1000, height: 1000 })
    expect(placementOf(300, 200, canvas, { fit: 'none', x: 10 })).toEqual({ x: 10, y: 300, width: 300, height: 200 })
    expect(placementOf(400, 200, canvas, { width: 200, x: 0, y: 0 })).toEqual({ x: 0, y: 0, width: 200, height: 100 })
  })
})

describe('fillBox', () => {
  it('fills the rest of the canvas for what is not given', () => {
    const canvas = { width: 1080, height: 1350 }
    expect(fillBox(canvas, {})).toEqual({ x: 0, y: 0, width: 1080, height: 1350 })
    expect(fillBox(canvas, { y: 500, height: 850 })).toEqual({ x: 0, y: 500, width: 1080, height: 850 })
    expect(fillBox(canvas, { x: 72, y: 1180, width: 240, height: 8 })).toEqual({ x: 72, y: 1180, width: 240, height: 8 })
  })
})

describe('arguments', () => {
  it('reads blend modes however they are written', () => {
    expect(blendFrom('soft light')).toBe('Soft Light')
    expect(blendFrom('LinearDodge(Add)')).toBe('Linear Dodge (Add)')
    expect(blendFrom('add')).toBe('Linear Dodge (Add)')
    expect(blendFrom(undefined)).toBeUndefined()
    expect(() => blendFrom('sparkle')).toThrow(/Blend modes/)
  })

  it('reads opacity as a fraction or a percentage', () => {
    expect(opacityFrom(0.4)).toBe(0.4)
    expect(opacityFrom(40)).toBe(0.4)
    expect(opacityFrom(250)).toBe(1)
    expect(opacityFrom('x')).toBeUndefined()
  })

  it('merges nested adjustment settings over the defaults', () => {
    const merged = mergeSettings({ hue: 0, exposureSettings: { exposure: 0, offset: 0, gamma: 1 } }, { exposureSettings: { exposure: 0.5 } })
    expect(merged).toEqual({ hue: 0, exposureSettings: { exposure: 0.5, offset: 0, gamma: 1 } })
  })
})

describe('text and shape arguments', () => {
  it('reads alignment and shape kinds however they are written', () => {
    expect(alignFrom('centre')).toBe('Center')
    expect(alignFrom('RIGHT')).toBe('Right')
    expect(alignFrom(undefined)).toBeUndefined()
    expect(() => alignFrom('justify')).toThrow(/left, center or right/)
    expect(shapeKindFrom('circle')).toEqual({ kind: 'Ellipse', rounded: false })
    expect(shapeKindFrom('Rounded Rectangle')).toEqual({ kind: 'Rectangle', rounded: true })
    expect(shapeKindFrom('rect')).toEqual({ kind: 'Rectangle', rounded: false })
    expect(() => shapeKindFrom('star')).toThrow(/rectangle, rounded, ellipse or line/)
  })

  it('turns font families with styles into PostScript-style names', () => {
    expect(fontNameFrom('Avenir Next Bold Italic')).toBe('AvenirNext-BoldItalic')
    expect(fontNameFrom('Helvetica Neue Extra Bold')).toBe('HelveticaNeue-ExtraBold')
    expect(fontNameFrom('Times New Roman')).toBe('TimesNewRoman')
    expect(fontNameFrom('Inter Light')).toBe('Inter-Light')
    expect(fontNameFrom('HelveticaNeue-Bold')).toBe('HelveticaNeue-Bold')
    expect(fontNameFrom('')).toBe('Helvetica')
  })

  it('runs a line from (x, y) by width and height', () => {
    expect(lineEnds({ x: 10, y: 20, width: 100 }, { width: 500, height: 400 })).toEqual([
      [10, 20],
      [110, 20]
    ])
    expect(lineEnds({}, { width: 500, height: 400 })).toEqual([
      [0, 200],
      [500, 200]
    ])
    expect(() => lineEnds({ x: 0, width: 0, height: 0 }, { width: 500, height: 400 })).toThrow(/length/)
  })

  it('describes text and shape layers', () => {
    const text = { ...pixelLayer('Title', new Raster(10, 10)), text: textStyle({ content: 'Hi', fontName: 'Georgia-Bold', fontSize: 40, alignment: 'Center' }) }
    const shape = { ...pixelLayer('Card', new Raster(10, 10)), shape: { kind: 'Rectangle' as const, cornerRadius: 8, red: 1, green: 0, blue: 0 } }
    const state: DocState = { width: 10, height: 10, resolution: 72, layers: [text, shape], activeLayerId: null, guides: [], selection: null }
    expect(describeLayer(state, text)).toMatchObject({ kind: 'text', text: 'Hi', font: 'Georgia-Bold', size: 40, align: 'center' })
    expect(describeLayer(state, shape)).toMatchObject({ kind: 'shape', shape: 'rounded rectangle' })
  })
})

describe('resize and crop arguments', () => {
  const canvas = { width: 1000, height: 500 }

  it('changes the canvas around an anchor, or scales the image', () => {
    expect(resizePlan(canvas, { width: 1200, height: 600 })).toEqual({ kind: 'canvas', width: 1200, height: 600, anchor: 'center' })
    expect(resizePlan(canvas, { width: 1200, anchor: 'top left' })).toEqual({ kind: 'canvas', width: 1200, height: 500, anchor: 'top-left' })
    expect(resizePlan(canvas, { scale: 0.5 })).toEqual({ kind: 'image', width: 500, height: 250, resample: true })
    expect(resizePlan(canvas, { image: true, width: 400, resample: false })).toEqual({ kind: 'image', width: 400, height: 200, resample: false })
    expect(() => resizePlan(canvas, {})).toThrow(/width and height/)
  })

  it('reads anchors however they are written', () => {
    expect(anchorFrom('bottom right')).toBe('bottom-right')
    expect(anchorFrom('right-bottom')).toBe('bottom-right')
    expect(anchorFrom('top centre')).toBe('top')
    expect(anchorFrom('middle')).toBe('center')
    expect(anchorFrom(undefined)).toBe('center')
    expect(() => anchorFrom('nowhere')).toThrow(/anchor is one of/)
  })

  it('keeps a crop box inside the canvas', () => {
    expect(cropBox(canvas, { x: 100, y: 50, width: 300, height: 200 })).toEqual({ x: 100, y: 50, width: 300, height: 200 })
    expect(cropBox(canvas, { x: 900, width: 500 })).toEqual({ x: 900, y: 0, width: 100, height: 500 })
    expect(() => cropBox(canvas, { x: 2000 })).toThrow(/outside/)
  })
})
