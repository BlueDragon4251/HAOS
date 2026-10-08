import { beforeEach, describe, expect, it, vi } from 'vitest'

const createChat = vi.fn(async (..._args: unknown[]) => ({ sessionId: 'legacy-session' }))
const sendPrompt = vi.fn()
const showPage = vi.fn()
const serviceInfo = vi.fn()
const request = vi.fn()
vi.mock('./chat.ts', () => ({ createChat: (...args: unknown[]) => createChat(...args), sendPrompt: (...args: unknown[]) => sendPrompt(...args) }))
vi.mock('./windows.ts', () => ({ showPage: (...args: unknown[]) => showPage(...args) }))
vi.mock('./durable-missions.ts', () => ({ refreshDurableMissions: vi.fn(async () => {}) }))

import { startMission } from './missions-actions.ts'

describe('mission submission', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('window', { heraldOS: { missions: { serviceInfo, request } } })
  })

  it('persists HAOS work through the controller with the same key on a transport retry', async () => {
    serviceInfo.mockResolvedValue({ managed: true })
    request.mockRejectedValueOnce(new Error('reply lost')).mockResolvedValueOnce({ id: 'stored-mission' })
    await expect(startMission('Build', 'request-key')).rejects.toThrow(/reply lost/)
    const row = await startMission('Build', 'request-key')
    expect(row).toEqual({ missionId: 'stored-mission', title: 'Build', queued: true })
    expect(request.mock.calls[0]).toEqual(request.mock.calls[1])
    expect(createChat).not.toHaveBeenCalled()
    expect(sendPrompt).not.toHaveBeenCalled()
    expect(showPage).toHaveBeenCalledWith('missions')
  })

  it('retains Herald compatibility when HAOS is explicitly disabled', async () => {
    serviceInfo.mockResolvedValue({ managed: false })
    const row = await startMission('Build')
    expect(row.sessionId).toBe('legacy-session')
    expect(row.queued).toBe(false)
    expect(request).not.toHaveBeenCalled()
    expect(sendPrompt).toHaveBeenCalled()
  })
})
