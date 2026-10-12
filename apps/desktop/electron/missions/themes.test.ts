import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ app: { getAppPath: () => path.resolve(__dirname, '../..') } }))
import { missionTheme } from './themes.ts'
import { findTheme } from '../theme/themes.ts'
import { MISSION_THEME_SDK, missionThemeName } from '../../shared/mission-theme.ts'

const mission = '42514251-0000-4000-8000-000000000003'
let home: string
beforeEach(() => { home = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-generated-theme-')); vi.spyOn(os, 'homedir').mockReturnValue(home) })
afterEach(() => { vi.restoreAllMocks(); fs.rmSync(home, { recursive: true, force: true }) })
const theme = () => ({ colors: Object.fromEntries(MISSION_THEME_SDK.colors.map(key => [key, key.startsWith('fg') ? '#dae7ff' : '#122136'])), label: 'Generated data fixture', shell: { theme: 'ocean', scheme: 'dark' } })

describe('mission-scoped existing theme publisher', () => {
  it('publishes actual complete revisions and preserves earlier bytes without activation', () => {
    const first = missionTheme({ mission, action: { operation: 'theme.stage', theme: theme() } })
    expect(first.name).toBe(missionThemeName(mission)); expect(first.scope).toBe('mission-data-theme')
    const bundle = findTheme(String(first.name), String(first.revision))!
    expect(bundle.spec.wallpaper).toBe('default'); expect(bundle.spec.colors.fg).toBe('#dae7ff')
    expect(JSON.parse(fs.readFileSync(path.join(bundle.dir, 'theme.json'), 'utf8')).name).toBe(first.name)
    const second = missionTheme({ mission, action: { operation: 'theme.stage', theme: { ...theme(), description: 'Actual second revision' } } })
    expect(second.revision).not.toBe(first.revision); expect(findTheme(String(first.name), String(first.revision))?.spec.description).toBeUndefined()
    expect(fs.existsSync(path.join(home, '.config/herald-os/prefs.json'))).toBe(false)
  })
  it('keeps different missions in distinct generated namespaces', () => {
    const a = missionTheme({ mission, action: { operation: 'theme.stage', theme: theme() } })
    const b = missionTheme({ mission: '42514251-0000-4000-8000-000000000004', action: { operation: 'theme.stage', theme: theme() } })
    expect(a.name).not.toBe(b.name); expect(a.revision).not.toBe(b.revision)
    expect(missionTheme({ mission, action: { operation: 'theme.sdk' } })).toEqual(MISSION_THEME_SDK)
  })
  it.each(['name', 'wallpaper', 'script', 'plugins', 'gtk', 'terminal'])('denies %s before creating observer files', field => {
    expect(() => missionTheme({ mission, action: { operation: 'theme.stage', theme: { ...theme(), [field]: '/etc/haos/secret' } } })).toThrow()
    expect(fs.readdirSync(home)).toEqual([])
  })
  it('rejects fake mission identities and caps actual saved versions', () => {
    expect(() => missionTheme({ mission: '../../owner', action: { operation: 'theme.sdk' } })).toThrow()
    for (let i = 0; i < 16; i++) missionTheme({ mission, action: { operation: 'theme.stage', theme: { ...theme(), description: String(i) } } })
    expect(() => missionTheme({ mission, action: { operation: 'theme.stage', theme: theme() } })).toThrow(/budget/)
  })
})
