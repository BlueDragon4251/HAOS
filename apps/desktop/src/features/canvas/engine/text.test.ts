import { describe, expect, it } from 'vitest'
import { defaultTransform, newManifest, parseManifest, serializeManifest } from '../../../../shared/canvas/comp-format.ts'
import { constrainShape, shapeBox, shapeName } from './shapes.ts'
import { fontCss, fontFace, layoutText, originForAnchor, originForTop, postScriptName, spacedFamily, type TextMeasure, textStyle, wrapLines } from './text.ts'

/** Every character 10 pixels wide, plus tracking. */
const monospace = (tracking = 0): TextMeasure => ({ width: (text) => text.length * (10 + tracking), ascent: 16, descent: 4 })

describe('font names', () => {
  it('reads families, weights and slants out of PostScript names', () => {
    expect(fontFace('HelveticaNeue-Bold')).toEqual({ family: 'Helvetica Neue', weight: 700, italic: false })
    expect(fontFace('SFProDisplay-SemiboldItalic')).toEqual({ family: 'SF Pro Display', weight: 600, italic: true })
    expect(fontFace('TimesNewRomanPSMT')).toEqual({ family: 'Times New Roman', weight: 400, italic: false })
    expect(fontFace('Inter-ExtraLight')).toEqual({ family: 'Inter', weight: 200, italic: false })
    expect(fontFace('Avenir Next')).toEqual({ family: 'Avenir Next', weight: 400, italic: false })
    expect(spacedFamily('PTSans')).toBe('PT Sans')
  })

  it('writes names back the same way', () => {
    expect(postScriptName({ family: 'Helvetica Neue', weight: 700, italic: false })).toBe('HelveticaNeue-Bold')
    expect(postScriptName({ family: 'Georgia', weight: 400, italic: false })).toBe('Georgia')
    expect(postScriptName({ family: 'Georgia', weight: 400, italic: true })).toBe('Georgia-Italic')
    expect(postScriptName({ family: 'Inter', weight: 600, italic: true })).toBe('Inter-SemiBoldItalic')
    expect(fontFace(postScriptName({ family: 'Avenir Next', weight: 500, italic: false }))).toEqual({ family: 'Avenir Next', weight: 500, italic: false })
    expect(fontCss('HelveticaNeue-BoldItalic', 48)).toBe('italic 700 48px "Helvetica Neue", system-ui, sans-serif')
  })
})

describe('text layout', () => {
  it('hangs point text from its first baseline, at the alignment edge', () => {
    const style = textStyle({ content: 'Hello\nHi', fontSize: 20 })
    const layout = layoutText(style, monospace())
    expect(layout.pad).toBe(5)
    expect(layout.width).toBe(60)
    expect(layout.lines.map((line) => [line.x, line.baseline])).toEqual([
      [5, 21],
      [5, 45]
    ])
    expect(layout.anchor).toEqual([5, 21])
    expect(originForAnchor(layout, 100, 100)).toEqual([95, 79])
    const centred = layoutText({ ...style, alignment: 'Center' }, monospace())
    expect(centred.lines[1].x).toBe(20)
    expect(centred.anchor[0]).toBe(30)
    expect(originForTop(centred, 100, 100)).toEqual([70, 95])
  })

  it('counts tracking, and leading from baseline to baseline (0 is 120% of the size)', () => {
    const layout = layoutText(textStyle({ content: 'ab\ncd', fontSize: 20, tracking: 2, leading: 30 }), monospace(2))
    expect(layout.lines[0].width).toBe(24)
    expect(layout.lineHeight).toBe(30)
    expect(layoutText(textStyle({ content: 'ab\ncd', fontSize: 20 }), monospace()).lineHeight).toBe(24)
  })

  it('wraps paragraph text inside its box', () => {
    expect(wrapLines('the quick brown fox', 100, (text) => text.length * 10)).toEqual(['the quick', 'brown fox'])
    expect(wrapLines('abcdefghijkl', 50, (text) => text.length * 10)).toEqual(['abcde', 'fghij', 'kl'])
    expect(wrapLines('one\n\ntwo', 100, (text) => text.length * 10)).toEqual(['one', '', 'two'])
    const layout = layoutText(textStyle({ content: 'the quick brown fox', fontSize: 20, boxSize: [100, 0], alignment: 'Right' }), monospace())
    expect(layout.lines.map((line) => line.text)).toEqual(['the quick', 'brown fox'])
    expect(layout.lines[0].x).toBe(10)
    expect([layout.width, layout.height]).toEqual([100, 44])
    expect(layout.anchor).toEqual([0, 0])
  })

  it('keeps text and its style in the manifest', () => {
    const manifest = newManifest(200, 100)
    const id = '6F1D2C3B-4A59-4E8F-9D7C-1B2A3C4D5E6F'
    const text = textStyle({ content: 'Night market', fontName: 'HelveticaNeue-Bold', fontSize: 64, red: 1, green: 0.7, blue: 0.28, alignment: 'Center', tracking: 1.5, leading: 4, boxSize: [400, 120] })
    manifest.layers.push({ id, name: 'Title', isVisible: true, transform: defaultTransform(400, 120, 10, 10), imageFile: `${id}.png`, text })
    const back = parseManifest(JSON.parse(serializeManifest(manifest)))
    expect(back.layers[0].text).toEqual(text)
  })
})

describe('shape boxes', () => {
  it('fills the dragged box, or leaves room around a line', () => {
    expect(shapeBox('Rectangle', [50, 40], [10, 20]).box).toEqual({ x: 10, y: 20, width: 40, height: 20 })
    const line = shapeBox('Line', [10, 10], [50, 10], 4)
    expect(line.box).toEqual({ x: 7, y: 7, width: 46, height: 6 })
    expect(line.start![0] * line.box.width + line.box.x).toBeCloseTo(10)
    expect(line.end![1] * line.box.height + line.box.y).toBeCloseTo(10)
  })

  it('squares boxes and snaps lines with Shift', () => {
    expect(constrainShape('Ellipse', [0, 0], [30, -10])).toEqual([30, -30])
    const [x, y] = constrainShape('Line', [0, 0], [100, 10])
    expect([Math.round(x), Math.round(y)]).toEqual([100, 0])
    expect(shapeName({ kind: 'Rectangle', cornerRadius: 12 })).toBe('Rounded Rectangle')
  })
})
