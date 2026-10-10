import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const location = vi.hoisted(() => ({ directory: '' }))
vi.mock('./paths.ts', () => ({ heraldOsDataDir: () => location.directory }))
import { readPrefs, writePrefs } from './prefs.ts'

beforeEach(() => { location.directory = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-prefs-atomic-')) })
afterEach(() => { vi.restoreAllMocks(); fs.rmSync(location.directory, { recursive: true, force: true }) })

it('atomically publishes private preferences while retaining unrelated settings', () => {
  writePrefs({ theme: 'ocean', favorites: ['retained'], accent: 'blue' })
  writePrefs({ theme: 'graphite', themeRevision: 'b'.repeat(64) })
  expect(readPrefs().theme).toBe('graphite')
  expect(readPrefs().favorites).toEqual(['retained'])
  expect(fs.statSync(path.join(location.directory, 'prefs.json')).mode & 0o777).toBe(0o600)
  expect(fs.readdirSync(location.directory)).toEqual(['prefs.json'])
})

it('preserves the previous complete file after a failed atomic replacement', () => {
  writePrefs({ theme: 'ocean' })
  const file = path.join(location.directory, 'prefs.json'), before = fs.readFileSync(file)
  vi.spyOn(fs, 'renameSync').mockImplementation(() => { throw new Error('injected atomic publication failure') })
  expect(() => writePrefs({ theme: 'graphite' })).toThrow('publication failure')
  expect(fs.readFileSync(file)).toEqual(before)
  expect(fs.readdirSync(location.directory)).toEqual(['prefs.json'])
})

it.each(['symlink', 'hardlink'])('rejects a %s destination without changing the linked file', kind => {
  const source = path.join(location.directory, 'unrelated.json'), file = path.join(location.directory, 'prefs.json')
  fs.writeFileSync(source, '{"theme":"ocean"}')
  if (kind === 'symlink') fs.symlinkSync(source, file)
  else fs.linkSync(source, file)
  expect(() => writePrefs({ theme: 'graphite' })).toThrow('Unsafe preferences')
  expect(fs.readFileSync(source, 'utf8')).toBe('{"theme":"ocean"}')
  expect(fs.readdirSync(location.directory).filter(name => name.startsWith('.prefs-'))).toEqual([])
})
