import { describe, expect, it } from 'vitest'
import type { ChatMessage } from '../chat-model.ts'
import { assistantTextSince, runningToolsSince, textDelta, toolsSince } from './turn-text.ts'

const messages: ChatMessage[] = [
  { id: 'a0', role: 'assistant', text: 'Earlier reply.', reasoning: '', streaming: false, ts: 1 },
  { id: 'u1', role: 'user', text: 'Open Safari', ts: 2 },
  { id: 'a1', role: 'assistant', text: 'Let me check.', reasoning: '', streaming: false, ts: 3 },
  { id: 't1', role: 'tool', toolId: 'x', name: 'system_open', running: true, ts: 4 },
  { id: 'a2', role: 'assistant', text: 'Safari is open.', reasoning: '', streaming: true, ts: 5 }
]

describe('turn text projection', () => {
  it('concatenates assistant text after the user message only', () => {
    expect(assistantTextSince(messages, 1)).toBe('Let me check.\n\nSafari is open.')
    expect(assistantTextSince(messages, -1)).toContain('Earlier reply.')
  })

  it('lists running tools after the user message', () => {
    expect(runningToolsSince(messages, 1)).toEqual(['system_open'])
    expect(runningToolsSince(messages, 3)).toEqual([])
  })

  it('lists every tool the turn used, finished ones too', () => {
    const finished: ChatMessage[] = [...messages.slice(0, 3), { id: 't1', role: 'tool', toolId: 'x', name: 'system_files', running: false, ts: 4 }]
    expect(runningToolsSince(finished, 1)).toEqual([])
    expect(toolsSince(finished, 1)).toEqual(['system_files'])
    expect(toolsSince(finished, 3)).toEqual([])
  })

  it('computes growth deltas and ignores rewrites', () => {
    expect(textDelta('Hello', 'Hello world')).toBe(' world')
    expect(textDelta('Hello', 'Hello')).toBe('')
    expect(textDelta('Hello', 'Bye now')).toBe('')
  })
})
