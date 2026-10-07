import { describe, expect, it } from 'vitest'
import { defaultAdjustment, defaultEffect, defaultTransform } from '../../../shared/canvas/comp-format.ts'
import {
  adjustmentSettings,
  adjustmentWith,
  alignFrom,
  anchorFrom,
  backgroundModeFrom,
  blendFrom,
  cropBox,
  describeLayer,
  describeLayers,
  effectKindFrom,
  effectsWith,
  fillBox,
  findByRef,
  fitPicture,
  fontNameFrom,
  fractionFrom,
  holeBox,
  jsonObject,
  lineEnds,
  maskActionFrom,
  maskPart,
  mergeSettings,
  opacityFrom,
  pictureFitFrom,
  placementOf,
  rangedArg,
  resizePlan,
  resolvePath,
  shapeKindFrom,
  shapeWith
} from './agent-model.ts'
import { adjustmentLayer, blankLayer, type DocState, folderLayer, insertLayer, pixelLayer, setClipped } from './engine/document.ts'
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

describe('adjustments, effects and masks for Hermes', () => {
  const black = () => ({ red: 0, green: 0, blue: 0 })
  const read = (value: unknown) => (value === '#ff0000' ? { red: 1, green: 0, blue: 0 } : value === 'navy' ? { red: 0, green: 0, blue: 0.5 } : black())

  it('takes JSON objects as objects or text', () => {
    expect(jsonObject('{"a": 1}', 'settings', '{}')).toEqual({ a: 1 })
    expect(jsonObject({ a: 2 }, 'settings', '{}')).toEqual({ a: 2 })
    expect(jsonObject(undefined, 'settings', '{}')).toEqual({})
    expect(() => jsonObject('[1]', 'effects', '{"stroke": false}')).toThrow(/effects must be a JSON object, like \{"stroke": false\}/)
    expect(() => jsonObject('{nope', 'settings', '{}')).toThrow(/JSON object/)
  })

  it('merges settings over an adjustment and checks them', () => {
    const exposure = defaultAdjustment('Exposure')
    const changed = adjustmentWith(exposure, { exposureSettings: { exposure: 0.6 } })
    expect(changed.exposureSettings).toEqual({ exposure: 0.6, offset: 0, gamma: 1 })
    expect(() => adjustmentWith(exposure, { exposureSettings: { exposure: 40 } })).toThrow(/exposure must be a number from -20 to 20/)
    expect(() => adjustmentWith(exposure, { kind: 'Invert' })).toThrow(/keeps its kind/)
    const map = adjustmentWith(defaultAdjustment('Gradient Map'), { gradientMapSettings: { shadows: 'navy' } }, read)
    expect(map.gradientMapSettings).toMatchObject({ shadows: { red: 0, green: 0, blue: 0.5 }, highlights: { red: 1, green: 1, blue: 1 } })
  })

  it('shows Hermes the settings each kind uses', () => {
    expect(adjustmentSettings(defaultAdjustment('Hue/Saturation'))).toEqual({ hue: 0, saturation: 0, lightness: 0, colorize: false })
    expect(adjustmentSettings(defaultAdjustment('Motion Blur'))).toEqual({ motionAngle: 0, motionDistance: 20 })
    expect(adjustmentSettings(defaultAdjustment('Invert'))).toEqual({})
    const layer = adjustmentLayer('Gaussian Blur', 10, 10)
    const state: DocState = { width: 10, height: 10, resolution: 72, layers: [layer], activeLayerId: null, guides: [], selection: null }
    expect(describeLayer(state, layer)).toMatchObject({ kind: 'adjustment', adjustment: 'Gaussian Blur', settings: { blurRadius: 8 } })
  })

  it('adds, merges, hides and removes effects', () => {
    expect(effectKindFrom('Drop Shadow')).toBe('shadow')
    expect(effectKindFrom('glow')).toBe('outerGlow')
    expect(() => effectKindFrom('bevel')).toThrow(/Effects: stroke, shadow/)
    const added = effectsWith(undefined, { shadow: { distance: 12, color: '#ff0000', opacity: 40 }, stroke: true }, read)!
    expect(added.shadow).toEqual({ ...defaultEffect.shadow(), distance: 12, red: 1, green: 0, blue: 0, opacity: 0.4 })
    expect(added.stroke).toEqual({ ...defaultEffect.stroke(), enabled: true })
    const hidden = effectsWith(added, { shadow: { enabled: false } })!
    expect(hidden.shadow).toEqual({ ...added.shadow, enabled: false })
    const removed = effectsWith(hidden, { shadow: false, stroke: null })
    expect(removed).toBeUndefined()
    // Effects another app wrote stay as they were.
    expect(effectsWith({ satin: { size: 3 } } as never, { stroke: false })).toEqual({ satin: { size: 3 } })
    expect(() => effectsWith(undefined, { stroke: { size: 900 } })).toThrow(/size must be a number from 0 to 500/)
    expect(() => effectsWith(undefined, { stroke: 4 })).toThrow(/takes an object/)
  })

  it('reads mask actions however they are written', () => {
    expect(maskActionFrom('reveal all')).toBe('reveal')
    expect(maskActionFrom('hide_selection')).toBe('hideSelection')
    expect(maskActionFrom('revealSelection')).toBe('revealSelection')
    expect(maskActionFrom('off')).toBe('disable')
    expect(maskActionFrom('Delete')).toBe('remove')
    expect(() => maskActionFrom('feather')).toThrow(/Mask actions: reveal, hide/)
  })

  it('describes effects and unlinked masks', () => {
    const layer = { ...pixelLayer('Logo', new Raster(4, 4)), effects: { stroke: defaultEffect.stroke() }, mask: Raster.filled(1, 1, 255, 1), maskLinked: false }
    const state: DocState = { width: 4, height: 4, resolution: 72, layers: [layer], activeLayerId: null, guides: [], selection: null }
    expect(describeLayer(state, layer)).toMatchObject({ mask: 'on', maskLinked: false, effects: { stroke: defaultEffect.stroke() } })
  })

  it("holds settings to Compositor's ranges, naming the field and the range", () => {
    expect(() => adjustmentWith(defaultAdjustment('Exposure'), { exposureSettings: { offset: 0.8 } })).toThrow('adjustment.exposureSettings.offset must be a number from -0.5 to 0.5 (it was 0.8)')
    expect(() => adjustmentWith(defaultAdjustment('Grain'), { grainSettings: { size: 40 } })).toThrow(/grainSettings\.size must be a number from 0\.5 to 20/)
    expect(() => effectsWith(undefined, { shadow: { distance: 8000 } })).toThrow(/shadow\.distance must be a number from 0 to 5000/)
    expect(rangedArg(undefined, 'size', 'fontSize')).toBeUndefined()
    expect(rangedArg(120, 'size', 'fontSize')).toBe(120)
    expect(() => rangedArg(4000, 'size (the font size)', 'fontSize', ' pixels')).toThrow('size (the font size) must be from 1 to 2000 pixels (it was 4000)')
    expect(() => rangedArg(-24, 'leading', 'leading')).toThrow(/leading must be from 0 to 5000/)
  })

  it('fits a placed picture to its box, and finds the part of a mask under it', () => {
    const box = { x: 100, y: 50, width: 400, height: 200 }
    expect(pictureFitFrom(undefined)).toBe('cover')
    expect(pictureFitFrom('Contain')).toBe('contain')
    expect(() => pictureFitFrom('none')).toThrow(/cover .* contain .* stretch/)
    expect(fitPicture(1000, 1000, box, 'cover')).toEqual({ crop: { x: 0, y: 250, width: 1000, height: 500 }, box })
    expect(fitPicture(1000, 1000, box, 'contain')).toEqual({ crop: { x: 0, y: 0, width: 1000, height: 1000 }, box: { x: 200, y: 50, width: 200, height: 200 } })
    expect(fitPicture(10, 10, box, 'stretch').box).toBe(box)
    expect(maskPart(800, 400, box, { x: 200, y: 50, width: 200, height: 200 })).toEqual({ x: 200, y: 0, width: 400, height: 400 })
    expect(maskPart(400, 200, box, box)).toEqual({ x: 0, y: 0, width: 400, height: 200 })
  })

  it('reads the on-device tools’ arguments', () => {
    expect(backgroundModeFrom(undefined)).toBe('mask')
    expect(backgroundModeFrom('cut-out')).toBe('cutout')
    expect(() => backgroundModeFrom('erase')).toThrow(/mask .* or cutout/)
    expect(fractionFrom(40, 'threshold')).toBe(0.4)
    expect(fractionFrom(0.3, 'threshold')).toBe(0.3)
    expect(() => fractionFrom(-1, 'threshold')).toThrow(/threshold is from 0 to 1/)
    expect(holeBox({ width: 1000, height: 800 }, {})).toBeNull()
    expect(holeBox({ width: 1000, height: 800 }, { x: 900, y: -20, width: 300, height: 100 })).toEqual({ x: 900, y: 0, width: 100, height: 80 })
    expect(() => holeBox({ width: 1000, height: 800 }, { x: 10, y: 10 })).toThrow(/whole box/)
    expect(() => holeBox({ width: 1000, height: 800 }, { x: 2000, y: 0, width: 10, height: 10 })).toThrow(/outside/)
  })

  it('never clips a layer to an adjustment layer', () => {
    let state: DocState = { width: 10, height: 10, resolution: 72, layers: [], activeLayerId: null, guides: [], selection: null }
    const grade = adjustmentLayer('Curves', 10, 10)
    state = insertLayer(state, grade, {})
    const photo = pixelLayer('Photo', new Raster(10, 10))
    state = insertLayer(state, photo, { above: grade.id })
    expect(setClipped(state, photo.id, true)).toBe(state)
  })
})

describe('restyling shapes', () => {
  const box = { width: 400, height: 100 }
  const colour = (value: unknown) => (value === '#ff0000' ? { red: 1, green: 0, blue: 0 } : { red: 0, green: 0, blue: 0 })
  const rectangle = { kind: 'Rectangle' as const, cornerRadius: 0, red: 0, green: 0, blue: 0 }

  it('changes the kind, keeping the box: rounded gets a radius, a line runs corner to corner inside it', () => {
    expect(shapeWith(rectangle, { kind: 'rounded' }, box, colour).style).toMatchObject({ kind: 'Rectangle', cornerRadius: 15 })
    const line = shapeWith(rectangle, { kind: 'line' }, box, colour)
    expect(line.style).toMatchObject({ kind: 'Line', cornerRadius: 0, lineWidth: 4 })
    expect(line.style.start![0]).toBeCloseTo(3 / 400)
    expect(line.style.end![1]).toBeCloseTo(1 - 3 / 100)
    expect(line.changes).toEqual(['a line'])
    const back = shapeWith(line.style, { kind: 'ellipse' }, box, colour).style
    expect(back).toEqual({ kind: 'Ellipse', cornerRadius: 0, red: 0, green: 0, blue: 0 })
  })

  it('changes the colour, radius and line width within their bounds, and says what fits which kind', () => {
    expect(shapeWith(rectangle, { color: '#ff0000', radius: 500 }, box, colour)).toEqual({ style: { ...rectangle, red: 1, cornerRadius: 50 }, changes: ['colour', 'corner radius 50'] })
    const line = { kind: 'Line' as const, cornerRadius: 0, red: 0, green: 0, blue: 0, lineWidth: 4, start: [0, 0.5] as [number, number], end: [1, 0.5] as [number, number] }
    expect(shapeWith(line, { lineWidth: 0 }, box, colour).style.lineWidth).toBe(1)
    expect(() => shapeWith(rectangle, { lineWidth: 3 }, box, colour)).toThrow(/lineWidth is for lines/)
    expect(() => shapeWith(line, { radius: 3 }, box, colour)).toThrow(/radius rounds a rectangle/)
    expect(() => shapeWith(rectangle, {}, box, colour)).toThrow(/Nothing to change/)
  })

  it('describes a shape’s style for Hermes', () => {
    const layer = { ...pixelLayer('Panel', new Raster(40, 20), defaultTransform(40, 20)), shape: { kind: 'Rectangle' as const, cornerRadius: 6, red: 1, green: 0.5, blue: 0 } }
    const state: DocState = { width: 100, height: 100, resolution: 72, layers: [layer], activeLayerId: null, guides: [], selection: null }
    expect(describeLayer(state, layer)).toMatchObject({ kind: 'shape', shape: 'rounded rectangle', color: '#ff8000', radius: 6 })
  })
})
