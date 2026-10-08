import { describe, expect, it, vi } from 'vitest'
import type { CaptureFrame } from './audio-capture.ts'
import { ChainedEngine } from './chained-engine.ts'
import type { VoiceHost } from './engine.ts'
import { BARGE_IN_ENDPOINTER, Endpointer } from './vad.ts'

interface EngineInternals {
  mode: string
  endpointer: Endpointer
  transcribe: (pcm: Int16Array) => Promise<string>
  onFrame(frame: CaptureFrame): void
}

function fakeHost(answer: (text: string) => 'approve' | 'deny' | null, cardWaiting = true) {
  const calls = { interrupts: 0, intents: [] as string[], answers: [] as string[], captions: [] as unknown[] }
  const host: VoiceHost = {
    prefs: () => ({ followUpSeconds: 8 }) as ReturnType<VoiceHost['prefs']>,
    setState: () => undefined,
    setCaptions: patch => void calls.captions.push(patch),
    submit: async () => null,
    runIntent: async text => {
      calls.intents.push(text)

      return { handled: true, spoken: '', ok: true }
    },
    interrupt: async () => void calls.interrupts++,
    approvalPending: () => cardWaiting,
    answerApproval: text => {
      calls.answers.push(text)

      return cardWaiting ? answer(text) : null
    },
    observeTurn: () => () => undefined,
    ended: () => undefined,
    notify: () => undefined,
    recordLiveSeconds: () => undefined,
    setLiveSeconds: () => undefined
  }

  return { host, calls }
}

/** An engine in the middle of a Hermes turn: watching for barge-in, the reply not finished. */
function midTurn(host: VoiceHost): { engine: ChainedEngine; inner: EngineInternals } {
  const engine = new ChainedEngine(host)
  Object.assign(engine, { mode: 'monitor', turnDone: false, speak: { speaking: false, stop: () => undefined }, stopObserving: () => undefined, endpointer: new Endpointer(BARGE_IN_ENDPOINTER) })

  return { engine, inner: engine as unknown as EngineInternals }
}

const frame = (level: number): CaptureFrame => ({ pcm: new Int16Array(1600), level, ms: 100 })

describe('voice answers to an approval card during a turn', () => {
  it('approves with a short yes and lets the turn carry on', async () => {
    const { host, calls } = fakeHost(text => (text === 'Yes, go ahead.' ? 'approve' : null))
    const { engine, inner } = midTurn(host)
    await engine.submitTranscript('Yes, go ahead.')
    expect(calls.answers).toEqual(['Yes, go ahead.'])
    expect(calls.interrupts).toBe(0)
    expect(calls.intents).toEqual([])
    expect(inner.mode).toBe('monitor')
    expect(calls.captions).toContainEqual({ user: 'Yes, go ahead.', assistant: 'Approved.' })
  })

  it('still interrupts for anything else, which becomes the next request', async () => {
    const { host, calls } = fakeHost(() => null)
    const { engine } = midTurn(host)
    await engine.submitTranscript('put it in Receipts instead')
    expect(calls.interrupts).toBe(1)
    expect(calls.intents).toEqual(['put it in Receipts instead'])
  })

  it('hears speech over the turn out while a card waits, then decides it', async () => {
    const { host, calls } = fakeHost(text => (text === 'no' ? 'deny' : null))
    const { inner } = midTurn(host)
    inner.transcribe = async () => 'no'

    for (let i = 0; i < 4; i++) {
      inner.onFrame(frame(0.2))
    }

    expect(inner.mode).toBe('answer')
    expect(calls.interrupts).toBe(0)

    for (let i = 0; i < 10; i++) {
      inner.onFrame(frame(i < 2 ? 0.2 : 0))
    }

    await vi.waitFor(() => expect(calls.answers).toEqual(['no']))
    expect(calls.interrupts).toBe(0)
    expect(inner.mode).toBe('monitor')
  })

  it('barges in as before when no card waits', () => {
    const { host, calls } = fakeHost(() => null, false)
    const { inner } = midTurn(host)

    for (let i = 0; i < 4; i++) {
      inner.onFrame(frame(0.2))
    }

    expect(calls.interrupts).toBe(1)
    expect(inner.mode).toBe('listen')
  })
})
