import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ app: { getAppPath: () => path.resolve(__dirname, '../..') } }))

import { findTheme, listThemes, saveTheme, themeHistory } from './themes.ts'

let home: string
beforeEach(() => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-theme-validation-'))
  vi.spyOn(os, 'homedir').mockReturnValue(home)
})
afterEach(() => {
  vi.restoreAllMocks()
  fs.rmSync(home, { recursive: true, force: true })
})

describe('theme filesystem boundary', () => {
  it('publishes updates without deleting legacy data or earlier bundles', () => {
    const source = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../../../linux/themes/herald-ocean/theme.json'), 'utf8'))
    const name = 'my-safe-design'
    const legacy = path.join(home, '.config/herald-os/themes', name)
    fs.mkdirSync(legacy, { recursive: true })
    fs.writeFileSync(path.join(legacy, 'theme.json'), JSON.stringify({ ...source, name }))
    fs.writeFileSync(path.join(legacy, 'notes.txt'), 'Existing user content')
    saveTheme({ ...source, name, description: 'First saved version' })
    const first = findTheme(name)!
    saveTheme({ ...source, name, description: 'Second saved version' })
    const second = findTheme(name)!
    expect(first.revision).not.toBe(second.revision)
    expect(findTheme(name, first.revision)?.spec.description).toBe('First saved version')
    expect(themeHistory(name)).toHaveLength(2)
    expect(fs.readFileSync(path.join(legacy, 'notes.txt'), 'utf8')).toBe('Existing user content')
    fs.writeFileSync(path.join(second.dir, 'theme.json'), '{}')
    expect(findTheme(name)).toBeNull()
    expect(themeHistory(name)).toHaveLength(1)
    expect(findTheme(name, first.revision)?.spec.description).toBe('First saved version')
  })

  it('does not import a symlinked asset, manifest or directory', () => {
    const source = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../../../linux/themes/herald-ocean/theme.json'), 'utf8'))
    const base = path.join(home, '.config/herald-os/themes')
    fs.mkdirSync(base, { recursive: true })
    const secret = path.join(home, 'private.png')
    fs.writeFileSync(secret, 'owner data')
    for (const name of ['symlink-asset', 'symlink-manifest', 'symlink-directory']) {
      const folder = path.join(base, name)
      if (name === 'symlink-directory') {
        const outside = path.join(home, name)
        fs.mkdirSync(outside)
        fs.writeFileSync(path.join(outside, 'theme.json'), JSON.stringify({ ...source, name }))
        fs.symlinkSync(outside, folder)
      } else {
        fs.mkdirSync(folder)
        if (name === 'symlink-manifest') {
          const manifest = path.join(home, 'outside.json')
          fs.writeFileSync(manifest, JSON.stringify({ ...source, name }))
          fs.symlinkSync(manifest, path.join(folder, 'theme.json'))
        } else {
          fs.writeFileSync(path.join(folder, 'theme.json'), JSON.stringify({ ...source, name, wallpaper: 'wallpaper.png' }))
          fs.symlinkSync(secret, path.join(folder, 'wallpaper.png'))
        }
      }
    }
    expect(listThemes().filter(theme => theme.source === 'user')).toEqual([])
    expect(fs.readFileSync(secret, 'utf8')).toBe('owner data')
  })
})
