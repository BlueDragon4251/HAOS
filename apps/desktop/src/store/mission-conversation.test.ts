import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.fn()
const focus = vi.fn()
vi.mock('./missions.ts', () => ({ focusMissions: (...args: unknown[]) => focus(...args) }))
vi.mock('./durable-missions.ts', () => ({ refreshDurableMissions: vi.fn(async () => {}) }))
import { recoverMissionMessages, submitMissionMessage } from './mission-conversation.ts'

class MemoryStorage {
  data = new Map<string, string>()
  get length() { return this.data.size }
  key(index: number) { return [...this.data.keys()][index] ?? null }
  getItem(key: string) { return this.data.get(key) ?? null }
  setItem(key: string, value: string) { this.data.set(key, value) }
  removeItem(key: string) { this.data.delete(key) }
}

describe('durable local conversation admission', () => {
  let storage: MemoryStorage
  beforeEach(() => {
    vi.clearAllMocks()
    storage = new MemoryStorage()
    vi.stubGlobal('localStorage', storage)
    vi.stubGlobal('window', { heraldOS: { missions: { request } } })
  })

  it('persists an opaque intent before transmission, keeps text out of browser storage, and reuses a lost receipt', async () => {
    const text = 'Personal text that must not be persisted in renderer storage'
    request.mockImplementationOnce(async () => {
      expect(storage.length).toBe(1)
      expect([...storage.data.values()].join()).not.toContain(text)
      throw new Error('admission reply lost')
    })
    await expect(submitMissionMessage(text)).rejects.toThrow(/lost/)
    const first = request.mock.calls[0][1]
    const id = crypto.randomUUID()
    request.mockResolvedValueOnce({ id, idempotency_key: first.idempotency_key })
    await submitMissionMessage(text)
    expect(request.mock.calls[1]).toEqual(request.mock.calls[0])
    expect(first.idempotency_key).toMatch(/^[0-9a-f-]{36}$/)
    expect(storage.length).toBe(0)
    expect(focus).toHaveBeenCalledWith({ missionId: id })
  })

  it('checks a saved receipt after a new renderer loads without submitting another task', async () => {
    request.mockRejectedValueOnce(new Error('controller disconnected'))
    await expect(submitMissionMessage('Work')).rejects.toThrow(/disconnected/)
    const key = request.mock.calls[0][1].idempotency_key
    request.mockClear()
    const id = crypto.randomUUID()
    request.mockResolvedValueOnce({ id, idempotency_key: key })
    await recoverMissionMessages()
    expect(request.mock.calls).toEqual([['missions.lookup', { idempotency_key: key }]])
    expect(storage.length).toBe(0)
    expect(focus).toHaveBeenCalledWith({ missionId: id })
  })

  it('retains a pending intent when the reply belongs to another request', async () => {
    request.mockResolvedValueOnce({ id: crypto.randomUUID(), idempotency_key: crypto.randomUUID() })
    await expect(submitMissionMessage('Work')).rejects.toThrow(/unverified/)
    expect(storage.length).toBe(1)
    expect(focus).not.toHaveBeenCalled()
    request.mockResolvedValueOnce({ id: crypto.randomUUID(), idempotency_key: crypto.randomUUID() })
    await expect(recoverMissionMessages()).rejects.toThrow(/unverified/)
    expect(storage.length).toBe(1)
  })

  it('retains unresolved admission metadata without automatically resending', async () => {
    request.mockRejectedValueOnce(new Error('not acknowledged'))
    await expect(submitMissionMessage('Work')).rejects.toThrow()
    request.mockClear()
    request.mockResolvedValueOnce(null)
    await recoverMissionMessages()
    expect(request.mock.calls[0][0]).toBe('missions.lookup')
    expect(storage.length).toBe(1)
  })

  it('refuses to reuse a saved request for changed content', async () => {
    const key = crypto.randomUUID()
    request.mockRejectedValueOnce(new Error('lost'))
    await expect(submitMissionMessage('First task', key)).rejects.toThrow()
    request.mockClear()
    await expect(submitMissionMessage('Changed task', key)).rejects.toThrow(/different message/)
    expect(request).not.toHaveBeenCalled()
  })

  it('does not send when durable intent storage is unavailable', async () => {
    vi.spyOn(storage, 'setItem').mockImplementation(() => { throw new Error('storage unavailable') })
    await expect(submitMissionMessage('Work')).rejects.toThrow(/storage unavailable/)
    expect(request).not.toHaveBeenCalled()
  })

  it('keeps malformed pending metadata visible as an error without sending anything', async () => {
    storage.setItem('haos.pending-message.invalid', JSON.stringify({ key: 'invalid', digest: 'bad', at: 0 }))
    await expect(recoverMissionMessages()).rejects.toThrow(/inspection/)
    await expect(submitMissionMessage('Work')).rejects.toThrow(/inspection/)
    expect(request).not.toHaveBeenCalled()
  })
})
