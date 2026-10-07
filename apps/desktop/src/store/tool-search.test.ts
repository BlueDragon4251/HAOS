import { describe, expect, it } from 'vitest'
import { toolSearchOn } from './tool-search.ts'

describe('toolSearchOn', () => {
  it('reads tools.tool_search.enabled the way Hermes does', () => {
    expect(toolSearchOn({ tools: { tool_search: { enabled: 'off' } } })).toBe(false)
    expect(toolSearchOn({ tools: { tool_search: { enabled: false } } })).toBe(false)
    expect(toolSearchOn({ tools: { tool_search: { enabled: 'No' } } })).toBe(false)
    expect(toolSearchOn({ tools: { tool_search: { enabled: 'auto' } } })).toBe(true)
    expect(toolSearchOn({ tools: { tool_search: { enabled: 'on' } } })).toBe(true)
    // A typo falls back to Hermes's default, which is on.
    expect(toolSearchOn({ tools: { tool_search: { enabled: 'sometimes' } } })).toBe(true)
  })

  it('treats the legacy boolean and a missing section as Hermes does', () => {
    expect(toolSearchOn({ tools: { tool_search: false } })).toBe(false)
    expect(toolSearchOn({ tools: { tool_search: true } })).toBe(true)
    expect(toolSearchOn({})).toBe(true)
    expect(toolSearchOn(null)).toBe(true)
  })
})
