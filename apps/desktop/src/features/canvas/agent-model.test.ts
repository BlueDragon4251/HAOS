import { describe, expect, it } from 'vitest'
import { defaultTransform } from '../../../shared/canvas/comp-format.ts'
import { blendFrom, describeLayers, fillBox, findByRef, mergeSettings, opacityFrom, placementOf, resolvePath } from './agent-model.ts'
import { blankLayer, type DocState, folderLayer, insertLayer, pixelLayer, setClipped } from './engine/document.ts'
import { Raster } from './engine/raster.ts'

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
