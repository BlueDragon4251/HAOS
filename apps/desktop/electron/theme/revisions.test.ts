import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ThemeSpec } from '../../shared/theme.ts'
import { readThemeFile, ThemeRevisions } from './revisions.ts'

const source = path.resolve(__dirname, '../../../../linux/themes/herald-ocean/theme.json')
const theme: ThemeSpec = { ...JSON.parse(fs.readFileSync(source, 'utf8')), name: 'test-design', wallpaper: 'default' }
let home: string
let store: ThemeRevisions
beforeEach(() => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-theme-revisions-'))
  fs.chmodSync(home, 0o700)
  store = new ThemeRevisions(path.join(home, '.config/herald-os/theme-versions'), home)
})
afterEach(() => { vi.restoreAllMocks(); fs.rmSync(home, { recursive: true, force: true }) })

describe('complete theme revisions', () => {
  it('keeps both versions and exact assets across restart without overwriting the first', () => {
    const first = store.publish({ ...theme, wallpaper: 'wallpaper.png' }, Buffer.from('isolated opaque raster fixture'))
    const before = fs.readFileSync(path.join(first.dir, 'theme.json'))
    const second = store.publish({ ...theme, description: 'Changed', wallpaper: 'wallpaper.png' }, Buffer.from('different isolated fixture'))
    expect(second.revision).not.toBe(first.revision)
    expect(fs.readFileSync(path.join(first.dir, 'theme.json'))).toEqual(before)
    const reopened = new ThemeRevisions(store.root, home)
    expect(reopened.read(theme.name).revision).toBe(second.revision)
    expect(reopened.read(theme.name, first.revision).spec).toEqual(first.spec)
    expect(reopened.history(theme.name)).toHaveLength(2)
  })

  it('retains the current index when publication fails after staging a complete update', () => {
    const first = store.publish(theme)
    const rename = fs.renameSync
    vi.spyOn(fs, 'renameSync').mockImplementation((from, to) => {
      if (String(to).endsWith('/current.json')) throw new Error('isolated index write failure')
      rename(from, to)
    })
    expect(() => store.publish({ ...theme, description: 'New version' })).toThrow('isolated index write failure')
    expect(store.read(theme.name).revision).toBe(first.revision)
    expect(fs.readdirSync(path.dirname(first.dir)).some(name => name.startsWith('.stage-') || name.startsWith('.index-'))).toBe(false)
  })

  it('deduplicates identical complete bundles without changing their bytes', () => {
    const first = store.publish(theme)
    expect(store.publish(theme).revision).toBe(first.revision)
    expect(store.history(theme.name)).toHaveLength(1)
  })

  it('does not publish malformed manifests or missing wallpaper assets', () => {
    const first = store.publish(theme)
    expect(() => store.publish({ ...theme, colors: { ...theme.colors, fg: 'url(file:///etc/shadow)' } })).toThrow()
    expect(() => store.publish({ ...theme, wallpaper: 'missing.png' })).toThrow('missing')
    expect(store.read(theme.name).revision).toBe(first.revision)
  })

  it('detects changed manifest and image bytes, keeping the earlier version readable', () => {
    const first = store.publish(theme)
    const second = store.publish({ ...theme, wallpaper: 'wallpaper.png' }, Buffer.from('actual stored fixture bytes'))
    fs.writeFileSync(path.join(second.dir, 'wallpaper.png'), 'changed stored fixture bytes')
    expect(() => store.read(theme.name)).toThrow('checksum')
    expect(store.history(theme.name).map(item => item.revision)).toEqual([first.revision])
    expect(store.read(theme.name, first.revision).spec).toEqual(theme)
    fs.writeFileSync(path.join(first.dir, 'theme.json'), JSON.stringify({ ...theme, label: 'Altered' }))
    expect(() => store.read(theme.name, first.revision)).toThrow('checksum')
  })

  it('rejects index traversal, extra fields, and replacement symlinks', () => {
    const first = store.publish(theme)
    const index = path.join(path.dirname(first.dir), 'current.json')
    fs.writeFileSync(index, JSON.stringify({ schema: 1, revision: '../../secret' }))
    expect(() => store.read(theme.name)).toThrow('revision')
    fs.writeFileSync(index, JSON.stringify({ schema: 1, revision: first.revision, script: 'forbidden' }))
    expect(() => store.read(theme.name)).toThrow('index')
    fs.unlinkSync(index); fs.symlinkSync(path.join(first.dir, 'theme.json'), index)
    expect(() => store.read(theme.name)).toThrow()
  })

  it('rejects symlinked ancestors before creating or writing through them', () => {
    const outside = path.join(home, 'outside'); fs.mkdirSync(outside)
    fs.symlinkSync(outside, path.join(home, '.config'))
    expect(() => store.publish(theme)).toThrow('directory')
    expect(fs.readdirSync(outside)).toEqual([])
  })

  it('rejects hardlinked, symlinked and oversized imported assets', () => {
    const file = path.join(home, 'fixture.png'); fs.writeFileSync(file, 'fixture')
    fs.symlinkSync(file, path.join(home, 'link.png'))
    expect(() => readThemeFile(path.join(home, 'link.png'), 50)).toThrow()
    expect(() => readThemeFile(file, 2)).toThrow('Unsafe')
    fs.linkSync(file, path.join(home, 'hardlink.png'))
    expect(() => readThemeFile(file, 50)).toThrow('Unsafe')
  })

  it('lets the actual Linux engine read the exact bundle written by the native store', () => {
    const first = store.publish(theme)
    const second = store.publish({ ...theme, description: 'New native version' })
    const engine = path.resolve(__dirname, '../../../../linux/bin/herald-os-theme')
    const result = execFileSync('python3', ['-c', `
import importlib.machinery, importlib.util, json, os, sys
from pathlib import Path
loader=importlib.machinery.SourceFileLoader('theme_revision_probe', sys.argv[1])
spec=importlib.util.spec_from_loader(loader.name,loader)
module=importlib.util.module_from_spec(spec);loader.exec_module(module)
module.HOME=Path(sys.argv[2]);module.CONFIG=module.HOME/'.config';module.STATE=module.CONFIG/'herald-os'
module.THEME_DIRS=[module.STATE/'themes']
latest=module.find('test-design');old=module.find('test-design',sys.argv[3])
assert latest[0].name==sys.argv[4] and old[0].name==sys.argv[3]
assert latest[1]['description']=='New native version'
assert 'test-design' in module.all_themes()
os.environ['HERMES_HOME']=str(module.HOME/'isolated-agent-home')
module.gsettings=lambda *args:None
module.relay=lambda payload:False
assert module.apply('test-design',sys.argv[3])==0
assert (module.CONFIG/'niri/theme.kdl').read_text().find(old[1]['colors']['accent'])>=0
assert (module.STATE/'theme-revision').read_text().strip()==sys.argv[3]
assert (module.HOME/'isolated-agent-home/skins/herald-os.yaml').is_file()
print(json.dumps({'native_linux_revision_match':True,'old_revision_readable':True,'old_revision_config_rendered':True}))
`, engine, home, first.revision, second.revision], { encoding: 'utf8' })
    expect(JSON.parse(result.trim().split('\n').at(-1) as string)).toEqual({ native_linux_revision_match: true, old_revision_readable: true, old_revision_config_rendered: true })
  })
})
