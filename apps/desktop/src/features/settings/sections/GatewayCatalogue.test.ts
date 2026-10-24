import { describe, expect, it } from 'vitest'
import { GATEWAYS, HAOS_APPROVED_GATEWAYS } from './GatewayCatalogue.tsx'

describe('HAOS gateway status is not misleading', () => {
  it('includes the 22 inspected pinned Hermes plugins', () => {
    expect(GATEWAYS).toHaveLength(22)
    expect(new Set(GATEWAYS).size).toBe(22)
    expect(GATEWAYS).toContain('whatsapp')
    expect(GATEWAYS).toContain('matrix')
    expect(GATEWAYS).toContain('teams')
  })
  it('does not silently authorize unintegrated platforms', () => {
    expect([...HAOS_APPROVED_GATEWAYS].sort()).toEqual(['discord', 'mattermost', 'slack', 'telegram'])
    for (const p of GATEWAYS) {
      if (p !== 'discord' && p !== 'telegram' && p !== 'slack' && p !== 'mattermost') expect(HAOS_APPROVED_GATEWAYS.has(p)).toBe(false)
    }
  })
})
