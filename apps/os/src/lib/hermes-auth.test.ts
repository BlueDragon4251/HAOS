import { describe, expect, it } from 'vitest'
import { isAuthErrorText, parseActiveProvider } from './hermes-auth.ts'

describe('parseActiveProvider', () => {
  it('reads model.provider from the raw config', () => {
    expect(parseActiveProvider("model:\n  provider: nous\n  default: z-ai/glm-5.2\n  base_url: ''\nagent:\n  reasoning_effort: high\n")).toBe('nous')
    expect(parseActiveProvider('model:\n  default: gpt-5\n  provider: "openai-codex"\n')).toBe('openai-codex')
  })

  it('returns null when absent', () => {
    expect(parseActiveProvider('agent:\n  provider: not-the-model\n')).toBeNull()
    expect(parseActiveProvider('')).toBeNull()
  })
})

describe('isAuthErrorText', () => {
  it('matches sign-in failures only', () => {
    expect(isAuthErrorText('agent init failed: No access token found for Nous Portal login.')).toBe(true)
    expect(isAuthErrorText('Refresh session has been revoked (invalid_grant)')).toBe(true)
    expect(isAuthErrorText('Tool terminal timed out after 60s')).toBe(false)
    expect(isAuthErrorText(undefined)).toBe(false)
  })
})
