import { describe, expect, it } from 'vitest'
import { DEFAULT_ENDPOINTER, Endpointer } from './vad.ts'

const FRAME_MS = 20

function feedFrames(endpointer: Endpointer, level: number, ms: number): ReturnType<Endpointer['feed']>[] {
  const events: ReturnType<Endpointer['feed']>[] = []

  for (let t = 0; t < ms; t += FRAME_MS) {
    const event = endpointer.feed(level, FRAME_MS)

    if (event) {
      events.push(event)
    }
  }

  return events
}

describe('Endpointer', () => {
  it('starts on sustained speech and ends after the silence window', () => {
    const endpointer = new Endpointer(DEFAULT_ENDPOINTER)
    expect(feedFrames(endpointer, 0.003, 500)).toEqual([])
    expect(feedFrames(endpointer, 0.2, 400)).toEqual(['speech-start'])
    expect(endpointer.isSpeaking).toBe(true)
    // Short pauses inside an utterance do not end it.
    expect(feedFrames(endpointer, 0.003, DEFAULT_ENDPOINTER.silenceMs - 200)).toEqual([])
    expect(feedFrames(endpointer, 0.2, 200)).toEqual([])
    expect(feedFrames(endpointer, 0.003, DEFAULT_ENDPOINTER.silenceMs + FRAME_MS)).toEqual(['speech-end'])
    expect(endpointer.isSpeaking).toBe(false)
  })

  it('ignores clicks shorter than the minimum speech duration', () => {
    const endpointer = new Endpointer(DEFAULT_ENDPOINTER)
    expect(feedFrames(endpointer, 0.3, DEFAULT_ENDPOINTER.minSpeechMs - FRAME_MS)).toEqual([])
    expect(feedFrames(endpointer, 0.003, 200)).toEqual([])
    expect(endpointer.isSpeaking).toBe(false)
  })

  it('reports a timeout when nobody speaks', () => {
    const endpointer = new Endpointer({ ...DEFAULT_ENDPOINTER, maxWaitMs: 1000 })
    expect(feedFrames(endpointer, 0.002, 1000 + FRAME_MS)).toEqual(['timeout'])
  })

  it('adapts the noise floor so a noisy room needs louder speech', () => {
    const endpointer = new Endpointer(DEFAULT_ENDPOINTER)
    // Quiet room: a soft 0.02 level counts as speech.
    expect(feedFrames(endpointer, 0.02, 400)).toContain('speech-start')

    const noisy = new Endpointer(DEFAULT_ENDPOINTER)
    feedFrames(noisy, 0.01, 3000)
    expect(noisy.noiseFloor).toBeGreaterThan(0.008)
    expect(feedFrames(noisy, 0.02, 400)).toEqual([])
  })

  it('caps utterance length', () => {
    const endpointer = new Endpointer({ ...DEFAULT_ENDPOINTER, maxSpeechMs: 1000 })
    const events = feedFrames(endpointer, 0.3, 1400)
    expect(events[0]).toBe('speech-start')
    expect(events).toContain('speech-end')
  })

  it('markSpeaking enters the speaking state directly', () => {
    const endpointer = new Endpointer(DEFAULT_ENDPOINTER)
    endpointer.markSpeaking()
    expect(endpointer.isSpeaking).toBe(true)
    expect(feedFrames(endpointer, 0.002, DEFAULT_ENDPOINTER.silenceMs + FRAME_MS)).toEqual(['speech-end'])
  })
})
