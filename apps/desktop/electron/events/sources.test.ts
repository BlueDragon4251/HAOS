import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ powerMonitor: { on: () => undefined }, ipcMain: { handle: () => undefined } }))

const { batteryCrossing, networkKey } = await import('./sources.ts')
const { hookScripts } = await import('./hooks.ts')

describe('batteryCrossing', () => {
  it('fires once when the battery drops to 15% and re-arms after charging', () => {
    let armed = true
    const step = (percent: number, charging = false) => {
      const verdict = batteryCrossing(armed, { present: true, percent, charging })
      armed = verdict.armed

      return verdict.fire
    }

    expect(step(40)).toBe(false)
    expect(step(15)).toBe(true)
    expect(step(12)).toBe(false)
    expect(step(12, true)).toBe(false)
    expect(step(14)).toBe(true)
  })

  it('stays quiet without a battery', () => {
    expect(batteryCrossing(true, { present: false })).toEqual({ fire: false, armed: true })
    expect(batteryCrossing(true, undefined)).toEqual({ fire: false, armed: true })
  })
})

describe('networkKey', () => {
  it('changes when going offline or joining another Wi-Fi network', () => {
    const home = networkKey({ online: true, wifi: { connected: true, ssid: 'Home' } })

    expect(networkKey({ online: true, wifi: { connected: true, ssid: 'Home' } })).toBe(home)
    expect(networkKey({ online: true, wifi: { connected: true, ssid: 'Cafe' } })).not.toBe(home)
    expect(networkKey({ online: false })).not.toBe(home)
  })
})

describe('hookScripts', () => {
  it('runs executable scripts in name order, skipping samples and dotfiles', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'herald-hooks-'))
    const write = (name: string, mode: number) => fs.writeFileSync(path.join(dir, name), '#!/bin/sh\n', { mode })

    write('20-second', 0o755)
    write('10-first', 0o755)
    write('not-executable', 0o644)
    write('30-example.sample', 0o755)
    write('.hidden', 0o755)

    expect(hookScripts(dir).map(file => path.basename(file))).toEqual(['10-first', '20-second'])
    expect(hookScripts(path.join(dir, 'missing'))).toEqual([])
  })
})
