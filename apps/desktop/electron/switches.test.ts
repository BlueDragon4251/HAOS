import { describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ ipcMain: { handle: () => undefined }, powerMonitor: { getSystemIdleTime: () => 0 }, powerSaveBlocker: { start: () => 1, stop: () => undefined } }))

const { renderIdleConf } = await import('./switches.ts')
const { keepRecent } = await import('./notifications-history.ts')

describe('renderIdleConf', () => {
  it('writes seconds for herald-os-idle, with the screensaver only when it is on', () => {
    expect(renderIdleConf({})).toContain('screensaver=0\nlock=600\nscreen_off=900\nsuspend=0\n')
    expect(renderIdleConf({ screensaver: { enabled: true, afterMinutes: 3 }, idle: { lockAfter: 5, screenOffAfter: 20, suspendAfter: 60 } })).toContain('screensaver=180\nlock=300\nscreen_off=1200\nsuspend=3600\n')
  })
})

describe('keepRecent', () => {
  it('keeps a week of well-formed notifications', () => {
    const now = Date.parse('2026-10-06T12:00:00Z')
    const day = 24 * 60 * 60_000

    expect(keepRecent([{ id: 'a', ts: now - day }, { id: 'b', ts: now - 8 * day }, { id: 3, ts: now }, null, 'x'], now)).toEqual([{ id: 'a', ts: now - day }])
    expect(keepRecent({ not: 'a list' }, now)).toEqual([])
  })
})
