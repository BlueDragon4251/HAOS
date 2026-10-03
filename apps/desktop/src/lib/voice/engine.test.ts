import { describe, expect, it } from 'vitest'
import { describeTurnError } from './engine.ts'

describe('describeTurnError', () => {
  it('explains a revoked Hermes login without sending the user to a terminal', () => {
    const described = describeTurnError('agent init failed: No access token found for Nous Portal login.')
    expect(described.fixable).toBe(true)
    expect(described.kind).toBe('auth')
    expect(described.title).toBe('Hermes is signed out')
    expect(described.spoken).toContain('sign-in')
    expect(described.spoken).not.toContain('terminal')
  })

  it('recognises rate limits as transient', () => {
    expect(describeTurnError('429 rate limit exceeded').fixable).toBe(false)
  })

  it('falls back to the raw message', () => {
    const described = describeTurnError('something odd')
    expect(described.title).toBe('Hermes turn failed')
    expect(described.body).toBe('something odd')
  })
})
