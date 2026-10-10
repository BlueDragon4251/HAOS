import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.fn()
const rpc = vi.fn()
const serviceInfo = vi.fn()
vi.mock('./gateway.ts', () => ({ gatewayRequest: (...args: unknown[]) => rpc(...args), onAnyGatewayEvent: vi.fn() }))
vi.mock('./sessions.ts', () => ({ refreshSessions: vi.fn(), rememberRuntimeId: vi.fn() }))
vi.mock('./notifications.ts', () => ({ notify: vi.fn() }))
vi.mock('./missions.ts', () => ({ focusMissions: vi.fn() }))
vi.mock('./windows.ts', () => ({ showPage: vi.fn() }))
vi.mock('./durable-missions.ts', () => ({ refreshDurableMissions: vi.fn(async () => {}) }))
import { $managedMissions } from './mission-mode.ts'
import { resetChats, runSlash, sendPrompt } from './chat.ts'

describe('HAOS conversation routing', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetChats()
    $managedMissions.set(null)
    const data = new Map<string, string>()
    vi.stubGlobal('localStorage', { get length() { return data.size }, key: (i: number) => [...data.keys()][i] ?? null,
      getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => data.set(k, v), removeItem: (k: string) => data.delete(k) })
    vi.stubGlobal('window', { heraldOS: { missions: { serviceInfo, request } } })
  })

  it('sends ordinary and transcribed HAOS messages only to the durable controller', async () => {
    serviceInfo.mockResolvedValue({ managed: true })
    request.mockImplementation(async (_method, params) => ({ id: crypto.randomUUID(), idempotency_key: params.idempotency_key, session_id: null }))
    expect(await sendPrompt('Text task')).toBeNull()
    expect(await sendPrompt('Spoken task', { surface: 'voice-live' })).toBeNull()
    expect(request.mock.calls.map(call => call[0])).toEqual(['missions.create', 'missions.create'])
    expect(rpc).not.toHaveBeenCalled()
  })

  it('does not execute upstream authentication or model slash commands in HAOS', async () => {
    serviceInfo.mockResolvedValue({ managed: true })
    request.mockImplementation(async (_method, params) => ({ id: crypto.randomUUID(), idempotency_key: params.idempotency_key, session_id: null }))
    await runSlash('/login')
    expect(request.mock.calls[0][1].goal).toBe('/login')
    expect(rpc).not.toHaveBeenCalled()
  })

  it('never selects legacy execution when mode identification fails', async () => {
    serviceInfo.mockRejectedValue(new Error('IPC unavailable'))
    await expect(sendPrompt('Work')).rejects.toThrow(/IPC unavailable/)
    expect(rpc).not.toHaveBeenCalled()
    expect(request).not.toHaveBeenCalled()
  })

  it('preserves standalone Herald chat when Electron explicitly identifies that mode', async () => {
    serviceInfo.mockResolvedValue({ managed: false })
    rpc.mockResolvedValueOnce({ session_id: 'standalone', stored_session_id: 'saved' }).mockResolvedValueOnce({})
    expect(await sendPrompt('Work')).toBe('standalone')
    expect(rpc.mock.calls.map(call => call[0])).toEqual(['session.create', 'prompt.submit'])
    expect(request).not.toHaveBeenCalled()
  })
})
