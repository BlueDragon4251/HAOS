import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DurableMission } from '../../shared/missions.ts'
import { hermesCommands } from './hermes.ts'
import * as windows from '../store/windows.ts'

vi.hoisted(() => {
  Object.assign(globalThis, { window: { innerWidth: 1440, innerHeight: 900 } })
})

const mission = { id: 'stored-id', goal: 'Build project', state: 'queued', phase: 'pending' } as DurableMission
const request = vi.fn()
const serviceInfo = vi.fn(async () => ({ managed: true }))
const action = (id: string, args: Record<string, unknown>) => {
  const command = hermesCommands.find(command => command.id === id)
  if (!command) throw new Error('Missing command')
  return command.run(args, { source: 'ui' })
}

describe('HAOS mission queue control', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(windows, 'showPage').mockImplementation(() => {})
    serviceInfo.mockResolvedValue({ managed: true })
    vi.stubGlobal('window', { innerWidth: 1440, innerHeight: 900, heraldOS: { missions: { serviceInfo, request } } })
    request.mockImplementation(async (method: string) => {
      if (method === 'health') return { service: 'haos-controller', pending_requests: [] }
      if (method === 'missions.list') return [mission]
      if (method === 'missions.pause') return { ...mission, state: 'blocked', phase: 'paused-before-dispatch' }
      if (method === 'missions.resume') return mission
      throw new Error('Unexpected mutation')
    })
  })
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('holds a matched queue entry through the controller instead of cancelling or submitting a prompt', async () => {
    expect((await action('mission.pause', { name: mission.id })).ok).toBe(true)
    expect(request.mock.calls.filter(([method]) => !['health', 'missions.list'].includes(method)))
      .toEqual([['missions.pause', { id: mission.id }]])
  })

  it('propagates a controller claim conflict without cancelling the running execution', async () => {
    request.mockImplementation(async (method: string) => {
      if (method === 'health') return { pending_requests: [] }
      if (method === 'missions.list') return [mission]
      throw new Error('Only undispatched work can be paused')
    })
    await expect(action('mission.pause', { name: mission.id })).rejects.toThrow(/undispatched/)
    expect(request.mock.calls.some(([method]) => method === 'missions.cancel')).toBe(false)
  })

  it('refuses an ambiguous goal match before sending a mutation', async () => {
    request.mockImplementation(async (method: string) => method === 'health' ? { pending_requests: [] } : [mission, { ...mission, id: 'other-id' }])
    expect((await action('mission.pause', { name: 'project' })).ok).toBe(false)
    expect(request.mock.calls.every(([method]) => ['health', 'missions.list'].includes(method))).toBe(true)
  })

  it('does not report successful resume when the controller returns an expired mission', async () => {
    request.mockImplementation(async (method: string) => method === 'missions.resume' ? { ...mission, state: 'failed' } : method === 'health' ? { pending_requests: [] } : [mission])
    expect((await action('mission.resume', { id: mission.id })).ok).toBe(false)
    expect(request.mock.calls[0]).toEqual(['missions.resume', { id: mission.id }])
  })

  it('returns paused work only to the queue without a fresh mission admission', async () => {
    expect((await action('mission.resume', { id: mission.id })).ok).toBe(true)
    expect(request.mock.calls.filter(([method]) => !['health', 'missions.list'].includes(method)))
      .toEqual([['missions.resume', { id: mission.id }]])
  })

  it('keeps durable resume unavailable without an explicit HAOS service identity', async () => {
    serviceInfo.mockResolvedValue({ managed: false })
    expect((await action('mission.resume', { id: mission.id })).ok).toBe(false)
    expect(request).not.toHaveBeenCalled()
  })
})
