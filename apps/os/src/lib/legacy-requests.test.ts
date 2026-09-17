import { describe, expect, it } from 'vitest'
import { legacyRequestFromEvent, legacyResponseCalls } from './legacy-requests.ts'

describe('legacy request compatibility', () => {
  it('answers a legacy approval through approval.respond with the request id', () => {
    const calls = legacyResponseCalls('approval', 'sid1', { request_id: 'ap-1', command: 'x' }, { choice: 'once' })
    expect(calls).toEqual([{ method: 'approval.respond', params: { session_id: 'sid1', choice: 'once', all: false, request_id: 'ap-1' } }])
  })

  it('locks one clarify answer per question for batch prompts', () => {
    const calls = legacyResponseCalls('clarify', 's', { request_id: 'c1', questions: [{ qid: 'a' }, { qid: 'b' }] }, { answers: { a: 'yes' } })
    expect(calls.map(c => c.params.question_id)).toEqual(['a', 'b'])
    expect(calls[0].params.answer).toBe('yes')
    expect(calls[1].params.answer).toBe('')
  })

  it('maps sudo and secret values onto the legacy parameter names', () => {
    expect(legacyResponseCalls('sudo', 's', { request_id: 'r' }, { value: 'pw' })[0].params).toMatchObject({ password: 'pw' })
    expect(legacyResponseCalls('secret', 's', { request_id: 'r' }, { value: 'k' })[0].params).toMatchObject({ value: 'k' })
  })

  it('responds exactly once and declines on fail', async () => {
    const seen: string[] = []
    const request = legacyRequestFromEvent('approval', 's', { request_id: 'r' }, async (method, params) => {
      seen.push(`${method}:${String(params.choice)}`)
    })
    request.respond({ choice: 'deny' })
    request.respond({ choice: 'once' })
    request.fail(1, 'late')
    await Promise.resolve()
    expect(seen).toEqual(['approval.respond:deny'])
  })
})
