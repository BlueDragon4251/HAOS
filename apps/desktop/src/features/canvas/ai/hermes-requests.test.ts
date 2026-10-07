import { describe, expect, it } from 'vitest'
import { aspectFor, editRequest, generatedLayerRequest, generationBox, generativeFillRequest, layerLine, promptName } from './hermes-requests.ts'

const poster = { project: '/Users/me/Pictures/Herald Canvas/Poster.comp', name: 'Poster', width: 1080, height: 1350 }

describe('what Herald Canvas asks Hermes for', () => {
  it('picks the image tool aspect nearest a box, and names layers from prompts', () => {
    expect(aspectFor(1920, 1080)).toBe('landscape')
    expect(aspectFor(1080, 1920)).toBe('portrait')
    expect(aspectFor(500, 520)).toBe('square')
    expect(promptName('  a   paper lantern  ', 'x')).toBe('a paper lantern')
    expect(promptName('', 'Generated layer')).toBe('Generated layer')
    expect(promptName('x'.repeat(60), '')).toHaveLength(40)
  })

  it('works generative fill in the selection with room around it, inside the canvas', () => {
    expect(generationBox({ x: 100, y: 200, width: 400, height: 200 }, 1080, 1350)).toEqual({ x: 0, y: 150, width: 600, height: 300 })
    expect(generationBox({ x: 1000, y: 1300, width: 60, height: 40 }, 1080, 1350)).toEqual({ x: 968, y: 1268, width: 112, height: 82 })
  })

  it('asks for generative fill with the box, the files, the placing command and what to do without an image tool', () => {
    const text = generativeFillRequest({
      image: poster,
      prompt: 'a red umbrella',
      box: { x: 40, y: 600, width: 500, height: 300 },
      context: '/tmp/herald-canvas-ai/a/context.png',
      mask: '/tmp/herald-canvas-ai/a/mask.png',
      result: '/tmp/herald-canvas-ai/a/result.png'
    })
    expect(text).toContain('generative fill: "a red umbrella"')
    expect(text).toContain('project /Users/me/Pictures/Herald Canvas/Poster.comp, 1080×1350 pixels')
    expect(text).toContain('aspect_ratio "landscape"')
    expect(text).toContain('Save the picture as a PNG at /tmp/herald-canvas-ai/a/result.png')
    expect(text).toContain(
      'canvas action=place_image project="/Users/me/Pictures/Herald Canvas/Poster.comp" source="/tmp/herald-canvas-ai/a/result.png" x=40 y=600 width=500 height=300 fit=cover mask_image="/tmp/herald-canvas-ai/a/mask.png" name="Generative Fill: a red umbrella"'
    )
    expect(text).toContain('If you have no image generation tool, or it fails, say so plainly')
    expect(text).toContain('place nothing')
  })

  it('carries on the surroundings when the fill has no words, and leaves project out for an unsaved image', () => {
    const text = generativeFillRequest({ image: { ...poster, project: null }, prompt: ' ', box: { x: 0, y: 0, width: 64, height: 64 }, context: '/tmp/c.png', mask: '/tmp/m.png', result: '/tmp/r.png' })
    expect(text).toContain('carry on what is around the selection')
    expect(text).toContain('not saved yet: the image in front, so leave project out')
    expect(text).toContain('canvas action=place_image source="/tmp/r.png"')
    expect(text).not.toContain('project=')
  })

  it('asks for a generated layer in the selection, or fitted to the canvas', () => {
    const boxed = generatedLayerRequest({ image: poster, prompt: 'a paper lantern glowing orange', box: { x: 700, y: 100, width: 300, height: 400 }, result: '/tmp/r.png' })
    expect(boxed).toContain('new generated layer in "Poster"')
    expect(boxed).toContain('aspect_ratio "portrait"')
    expect(boxed).toContain('source="/tmp/r.png" x=700 y=100 width=300 height=400 fit=contain name="a paper lantern glowing orange"')
    expect(boxed).toContain('Layer > Remove Background')
    const whole = generatedLayerRequest({ image: poster, prompt: 'stars', box: null, result: '/tmp/r.png' })
    expect(whole).toContain('it fills the canvas')
    expect(whole).toContain('source="/tmp/r.png" fit=contain name="stars"')
    expect(whole).toContain('If you have no image generation tool')
  })

  it('asks for an edit with the layers, the selection, a preview and how to plan it', () => {
    const lines = [layerLine({ name: 'Headline', kind: 'text', opacity: 0.8, blend: 'Multiply' }), layerLine({ name: 'Grade', kind: 'adjustment', adjustment: 'Curves', visible: false, clippedTo: 'Photo' }), layerLine({ name: 'Photo', kind: 'pixels', mask: 'on', folder: 'Hero' })]
    expect(lines).toEqual(['Headline: text, 80%, Multiply', 'Grade: adjustment, Curves, hidden, clipped to Photo', 'Photo: pixels, mask on, in Hero'])
    const text = editRequest({ image: poster, request: 'make it moodier', layers: lines, selection: { x: 10, y: 20, width: 30, height: 40 }, preview: '/tmp/p.png' })
    expect(text).toContain('asks: "make it moodier"')
    expect(text).toContain('- Headline: text, 80%, Multiply')
    expect(text).toContain('selected 30×40 pixels from x 10, y 20')
    expect(text).toContain('The image as it is now: /tmp/p.png')
    expect(text).toContain('with the canvas tool on project="/Users/me/Pictures/Herald Canvas/Poster.comp"')
    expect(text).toContain('Prefer adjustment layers')
    expect(text).toContain('canvas action=preview before you start')
    expect(text).toContain('tell the person briefly what you changed')
  })

  it('lists at most thirty layers', () => {
    const text = editRequest({ image: poster, request: 'tidy up', layers: Array.from({ length: 34 }, (_, i) => `Layer ${i}: pixels`), selection: null, preview: null })
    expect(text).toContain('- Layer 29: pixels')
    expect(text).not.toContain('- Layer 30: pixels')
    expect(text).toContain('…and 4 more')
  })
})
