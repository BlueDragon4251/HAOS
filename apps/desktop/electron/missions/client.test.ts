import { describe, expect, it } from 'vitest'
import { managedMissions, missionSocket } from './client.ts'

describe('mission service selection', () => {
  it('keeps HAOS enabled even if its service is unavailable and refuses arbitrary socket paths', () => {
    expect(managedMissions({})).toBe(false)
    expect(managedMissions({ HAOS_BACKEND_CONFIG: '/etc/haos/backend.json' })).toBe(true)
    const env = { HAOS_BACKEND_CONFIG: '/etc/haos/backend.json', HAOS_CONTROL_SOCKET: '/run/haos-control/control.sock' }
    expect(missionSocket(env)).toBe(env.HAOS_CONTROL_SOCKET)
    expect(() => missionSocket({ ...env, HAOS_CONTROL_SOCKET: '/run/docker.sock' })).toThrow(/not configured/)
    expect(() => missionSocket({ HAOS_CONTROL_SOCKET: env.HAOS_CONTROL_SOCKET })).toThrow(/not configured/)
  })
})
