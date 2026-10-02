import { describe, expect, it } from 'vitest'
import { delegationPrompt, type LiveTranscriptFragment, reduceLiveEvent } from './live-engine.ts'

describe('reduceLiveEvent', () => {
  it('maps the vendor events the engine reacts to', () => {
    expect(reduceLiveEvent(JSON.stringify({ type: 'session.started', session: { id: 's1' } }))).toEqual({ kind: 'started', sessionId: 's1' })
    expect(reduceLiveEvent(JSON.stringify({ type: 'session.input_transcript.delta', delta: 'open ', start_ms: 10, end_ms: 400 }))).toEqual({
      kind: 'transcript',
      fragment: { speaker: 'user', text: 'open ', startMs: 10, endMs: 400 }
    })
    expect(reduceLiveEvent(JSON.stringify({ type: 'session.delegation.created', delegation: { id: 'item_1', type: 'delegation', target: 'client' } }))).toEqual({ kind: 'delegation', id: 'item_1' })
    expect(reduceLiveEvent(JSON.stringify({ type: 'session.closed', reason: 'idle', usage: { seconds: 42 } }))).toEqual({ kind: 'closed', reason: 'idle', usageSeconds: 42 })
  })

  it('marks late-append errors as ignorable', () => {
    expect(reduceLiveEvent(JSON.stringify({ type: 'error', error: { code: 'context_injection_incomplete', message: 'late' } }))).toEqual({ kind: 'error', message: 'late', ignorable: true })
    expect(reduceLiveEvent(JSON.stringify({ type: 'error', error: { message: 'boom' } }))).toEqual({ kind: 'error', message: 'boom', ignorable: false })
  })

  it('ignores unknown and malformed events', () => {
    expect(reduceLiveEvent(JSON.stringify({ type: 'response.output.delta' }))).toEqual({ kind: 'ignore' })
    expect(reduceLiveEvent('not json')).toEqual({ kind: 'ignore' })
  })
})

describe('delegationPrompt', () => {
  it('uses the last user turn as the prompt and the exchange as context', () => {
    const context: LiveTranscriptFragment[] = [
      { speaker: 'user', text: 'What time ', startMs: 0, endMs: 500 },
      { speaker: 'user', text: 'is it in Tokyo?', startMs: 500, endMs: 1200 },
      { speaker: 'assistant', text: 'Let me check that.', startMs: 1300, endMs: 2000 },
      { speaker: 'user', text: 'And Sydney too.', startMs: 2100, endMs: 2800 }
    ]
    const { prompt, voiceContext } = delegationPrompt(context)
    expect(prompt).toBe('And Sydney too.')
    expect(voiceContext.split('\n')).toEqual(['User: What time is it in Tokyo?', 'Voice assistant: Let me check that.', 'User: And Sydney too.'])
  })

  it('falls back to the transcript tail when the user said nothing', () => {
    const { prompt } = delegationPrompt([{ speaker: 'assistant', text: 'Hello!', startMs: 0, endMs: 100 }])
    expect(prompt).toBe('Voice assistant: Hello!')
  })
})
