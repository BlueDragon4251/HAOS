/*
 * Text layers for Herald Canvas. A text layer is a pixel layer whose PNG shows the text, plus the
 * text and its style in the manifest, so it can be edited again (and Compositor reads the same
 * record). Fonts are kept by PostScript-style name ("HelveticaNeue-Bold"); lines are laid out here
 * from a measuring function, and drawn with a 2D canvas. Point text grows from where it was
 * clicked; paragraph text wraps inside its box.
 */

import { type TextAlignment, type TextStyle, type Vec2 } from '../../../../shared/canvas/comp-format.ts'
import { Raster } from './raster.ts'

// Fonts.

export interface FontFace {
  family: string
  weight: number
  italic: boolean
}

/** Style words in PostScript names and the weights they stand for, longest first so "SemiBold" wins over "Bold". */
const WEIGHT_WORDS: [string, number][] = [
  ['ExtraLight', 200],
  ['UltraLight', 200],
  ['ExtraBold', 800],
  ['UltraBold', 800],
  ['SemiBold', 600],
  ['DemiBold', 600],
  ['Semibold', 600],
  ['Hairline', 100],
  ['Regular', 400],
  ['Medium', 500],
  ['Normal', 400],
  ['Light', 300],
  ['Heavy', 900],
  ['Black', 900],
  ['Roman', 400],
  ['Thin', 100],
  ['Bold', 700],
  ['Book', 400]
]

const WEIGHT_NAMES: Record<number, string> = { 100: 'Thin', 200: 'ExtraLight', 300: 'Light', 400: 'Regular', 500: 'Medium', 600: 'SemiBold', 700: 'Bold', 800: 'ExtraBold', 900: 'Black' }

/** "HelveticaNeue" to "Helvetica Neue", "SFProDisplay" to "SF Pro Display"; "PSMT" and "MT" endings go. */
export function spacedFamily(name: string): string {
  return name
    .replace(/(PS)?MT$/, '')
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .trim()
}

/** The family, weight and slant a PostScript-style name stands for. */
export function fontFace(fontName: string): FontFace {
  const dash = fontName.indexOf('-')
  const base = dash < 0 ? fontName : fontName.slice(0, dash)
  let style = dash < 0 ? '' : fontName.slice(dash + 1)
  const italic = /(Italic|Oblique|It)$/.test(style)
  style = style.replace(/(Italic|Oblique|It)$/, '')
  const weight = WEIGHT_WORDS.find(([word]) => style.includes(word))?.[1] ?? 400
  // A name with spaces is a family name already.
  const family = /\s/.test(base) ? base.trim() : spacedFamily(base)

  return { family: family || 'Helvetica', weight, italic }
}

/** A PostScript-style name for a face: "Helvetica Neue" bold is "HelveticaNeue-Bold", a plain face just the family. */
export function postScriptName(face: FontFace): string {
  const base = face.family.replace(/\s+/g, '')
  const weight = WEIGHT_NAMES[Math.round(Math.max(100, Math.min(900, face.weight)) / 100) * 100] ?? 'Regular'
  const style = weight === 'Regular' ? (face.italic ? 'Italic' : '') : `${weight}${face.italic ? 'Italic' : ''}`

  return style ? `${base}-${style}` : base
}

/** A CSS font for a 2D canvas or a text field. */
export function fontCss(fontName: string, size: number): string {
  const face = fontFace(fontName)
  const family = face.family.replace(/["\\]/g, '')

  return `${face.italic ? 'italic ' : ''}${face.weight} ${size}px "${family}", system-ui, sans-serif`
}

// Layout.

/** Measures text in one font, with the style's tracking applied. */
export interface TextMeasure {
  width(text: string): number
  ascent: number
  descent: number
}

export interface TextLine {
  text: string
  width: number
  /** Where the line starts and its baseline, in the layer's own pixels. */
  x: number
  baseline: number
}

export interface TextLayout {
  /** The layer's box, in its own pixels. */
  width: number
  height: number
  lines: TextLine[]
  lineHeight: number
  /** Room around point text for glyphs that reach past their advance (italics, swashes). */
  pad: number
  /** The point the text hangs from: the first baseline at the alignment edge for point text, the box's top-left for paragraphs. */
  anchor: Vec2
}

export const isParagraph = (style: TextStyle): boolean => Boolean(style.boxSize && style.boxSize[0] > 0)

export const lineHeightOf = (style: TextStyle): number => Math.max(1, style.fontSize * 1.2 + style.leading)

/** Lines broken to fit a width: at spaces where it can, inside a word too long for a line alone. */
export function wrapLines(text: string, width: number, measure: (text: string) => number): string[] {
  const lines: string[] = []

  for (const paragraph of text.split('\n')) {
    let line = ''

    for (const word of paragraph.split(/(?<=\s)/)) {
      const candidate = line + word

      if (!line || measure(candidate.trimEnd()) <= width) {
        line = candidate
      } else {
        lines.push(line.trimEnd())
        line = word
      }

      // A word wider than the box breaks between letters.
      while (measure(line.trimEnd()) > width && line.trimEnd().length > 1) {
        let cut = line.length - 1

        while (cut > 1 && measure(line.slice(0, cut)) > width) {
          cut--
        }

        lines.push(line.slice(0, cut))
        line = line.slice(cut)
      }
    }

    lines.push(line.trimEnd())
  }

  return lines
}

/** Lay text out: its lines, where each goes, and the layer's box. */
export function layoutText(style: TextStyle, measure: TextMeasure): TextLayout {
  const lineHeight = lineHeightOf(style)
  const paragraph = isParagraph(style)

  if (paragraph) {
    const [boxWidth, boxHeight] = style.boxSize!
    const texts = wrapLines(style.content, boxWidth, (text) => measure.width(text))
    const lines = texts.map((text, i) => {
      const width = measure.width(text)

      return { text, width, x: alignedX(style.alignment, boxWidth, width, 0), baseline: measure.ascent + i * lineHeight }
    })
    const fitted = measure.ascent + measure.descent + Math.max(0, lines.length - 1) * lineHeight

    return { width: Math.max(1, Math.round(boxWidth)), height: Math.max(1, Math.round(boxHeight > 0 ? boxHeight : fitted)), lines, lineHeight, pad: 0, anchor: [0, 0] }
  }

  const pad = Math.ceil(style.fontSize * 0.15) + 2
  const texts = style.content.split('\n')
  const widths = texts.map((text) => measure.width(text))
  const textWidth = Math.max(0, ...widths)
  const lines = texts.map((text, i) => ({ text, width: widths[i], x: pad + alignedX(style.alignment, textWidth, widths[i], 0), baseline: pad + measure.ascent + i * lineHeight }))
  const height = pad * 2 + measure.ascent + measure.descent + (texts.length - 1) * lineHeight

  return {
    width: Math.max(1, Math.ceil(textWidth + pad * 2)),
    height: Math.max(1, Math.ceil(height)),
    lines,
    lineHeight,
    pad,
    anchor: [pad + alignedX(style.alignment, textWidth, 0, 0), pad + measure.ascent]
  }
}

/** Where a line starts in a span of `span` pixels, by alignment (for a zero-width line: the alignment edge). */
function alignedX(alignment: TextAlignment, span: number, width: number, start: number): number {
  return alignment === 'Center' ? start + (span - width) / 2 : alignment === 'Right' ? start + span - width : start
}

/** The layer's top-left when its anchor goes at a document point (a click with the Type tool puts the first baseline there). */
export const originForAnchor = (layout: TextLayout, x: number, y: number): Vec2 => [x - layout.anchor[0], y - layout.anchor[1]]

/** The layer's top-left so its text's top edge sits at `y`, and its alignment edge (left, centre or right) at `x`. */
export const originForTop = (layout: TextLayout, x: number, y: number): Vec2 => [x - layout.anchor[0], y - layout.pad]

// Drawing.

/** A measure for a style, from a 2D context (an offscreen canvas in the window). */
export function canvasMeasure(context: OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D, style: TextStyle): TextMeasure {
  context.font = fontCss(style.fontName, style.fontSize)
  context.letterSpacing = `${style.tracking}px`
  const metrics = context.measureText('Hgjy')

  return {
    width: (text) => (text ? context.measureText(text).width : 0),
    ascent: metrics.fontBoundingBoxAscent || style.fontSize * 0.8,
    descent: metrics.fontBoundingBoxDescent || style.fontSize * 0.25
  }
}

let measuring: OffscreenCanvasRenderingContext2D | null = null

/** Measure with a shared offscreen canvas (the window only). */
export function measureFor(style: TextStyle): TextMeasure {
  measuring ??= new OffscreenCanvas(1, 1).getContext('2d')!

  return canvasMeasure(measuring, style)
}

/** Make sure a face is loaded before drawing with it (system fonts are; web fonts may not be yet). */
export async function loadFont(style: TextStyle): Promise<void> {
  await globalThis.document?.fonts?.load(fontCss(style.fontName, style.fontSize)).catch(() => [])
}

/**
 * The text drawn at `scale` (pixels per layer pixel: a layer scaled up draws its text larger, so
 * it stays sharp). One colour, so colour stays exact where antialiasing thins the alpha.
 */
export function renderText(style: TextStyle, layout: TextLayout, scale: Vec2 = [1, 1]): Raster {
  const width = Math.max(1, Math.round(layout.width * scale[0]))
  const height = Math.max(1, Math.round(layout.height * scale[1]))
  const canvas = new OffscreenCanvas(width, height)
  const context = canvas.getContext('2d', { willReadFrequently: true })!
  context.scale(width / layout.width, height / layout.height)
  context.font = fontCss(style.fontName, style.fontSize)
  context.letterSpacing = `${style.tracking}px`
  context.fillStyle = '#fff'
  context.textBaseline = 'alphabetic'

  for (const line of layout.lines) {
    context.fillText(line.text, line.x, line.baseline)
  }

  const pixels = context.getImageData(0, 0, width, height).data
  const raster = new Raster(width, height, 4, pixels)
  tint(raster, Math.round(style.red * 255), Math.round(style.green * 255), Math.round(style.blue * 255))

  return raster
}

/** One colour over a raster's alpha. */
export function tint(raster: Raster, r: number, g: number, b: number): void {
  const { data } = raster

  for (let i = 0; i < data.length; i += 4) {
    data[i] = r
    data[i + 1] = g
    data[i + 2] = b
  }
}

/** A text style with what is not given filled in. */
export function textStyle(patch: Partial<TextStyle> & { content: string }): TextStyle {
  return { fontName: 'Helvetica', fontSize: 72, red: 0, green: 0, blue: 0, alignment: 'Left', tracking: 0, leading: 0, ...patch }
}
