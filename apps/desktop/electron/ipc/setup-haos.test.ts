import fs from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IPC } from '../../shared/ipc.ts'

vi.mock('electron', () => ({ ipcMain: { handle: vi.fn() } }))
const { ipcMain } = await import('electron')
const { registerSetupIpc, setupState } = await import('./setup.ts')

afterEach(() => {
  vi.restoreAllMocks()
  vi.mocked(ipcMain.handle).mockClear()
})

describe('HAOS observer account onboarding', () => {
  it('detects HAOS first boot independently from classic Herald', () => {
    vi.spyOn(fs, 'existsSync').mockImplementation(file => (
      String(file) === '/etc/haos/enabled' || String(file) === '/var/lib/herald-os/firstboot-done'
    ))
    expect(setupState()).toMatchObject({ needed: process.platform === 'linux', haosManaged: true })
  })

  it('never invokes passwd on the locked observer account', async () => {
    vi.spyOn(fs, 'existsSync').mockImplementation(file => String(file) === '/etc/haos/enabled')
    registerSetupIpc()
    const callback = vi.mocked(ipcMain.handle).mock.calls.find(call => call[0] === IPC.setupPassword)?.[1]
    expect(callback).toBeDefined()
    const answer = await callback!(null as never, 'test-not-a-real-password')
    expect(answer).toMatchObject({ ok: false })
    expect(answer.error).toMatch(/trusted tty2 console/i)
  })
})


describe('managed HAOS completion cannot bypass root owner recovery readiness', () => {
  it('refuses to persist the done marker while service is not ready', async () => {
    vi.spyOn(fs, 'existsSync').mockImplementation(file => String(file) === '/etc/haos/enabled')
    const write = vi.spyOn(fs, 'writeFileSync')
    registerSetupIpc()
    const callback = vi.mocked(ipcMain.handle).mock.calls.find(call => call[0] === IPC.setupFinish)?.[1]
    expect(callback).toBeDefined()
    const result = await callback!(null as never, {})
    expect(result).toMatchObject({ ok: false })
    expect(write).not.toHaveBeenCalled()
  })
})
