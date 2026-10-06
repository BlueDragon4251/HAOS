import { describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ BrowserWindow: { getAllWindows: () => [] }, ipcMain: { handle: vi.fn(), on: vi.fn() } }))

const { nodeSocketAddress } = await import('./notification-daemon.ts')

describe('nodeSocketAddress', () => {
  it('keeps dbus-next on Node sockets for path addresses', () => {
    expect(nodeSocketAddress('unix:path=/run/user/1000/bus')).toBe('unix:socket=/run/user/1000/bus')
    expect(nodeSocketAddress('unix:path=/run/user/1000/bus,guid=abc;unix:abstract=/tmp/x')).toBe('unix:socket=/run/user/1000/bus')
  })

  it('maps abstract sockets to a NUL-prefixed path', () => {
    expect(nodeSocketAddress('unix:abstract=/tmp/dbus-XYZ,guid=1')).toBe('unix:socket=\u0000/tmp/dbus-XYZ')
  })

  it('falls back to the runtime-dir bus, and leaves other transports alone', () => {
    expect(nodeSocketAddress(undefined)).toMatch(/^unix:socket=\/run\/user\/\d+\/bus$/)
    expect(nodeSocketAddress('tcp:host=127.0.0.1,port=1234')).toBe('tcp:host=127.0.0.1,port=1234')
  })
})
