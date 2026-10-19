/** Actual Electron/Chromium render gate; all data and profiles are disposable. */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { app, nativeImage } from 'electron'

assert.equal(process.env.HAOS_DISPOSABLE_SCREEN_TEST, '1')
assert.notEqual(process.getuid(), 0)
app.enableSandbox()
app.on('window-all-closed', () => {})
let completed = false
app.on('before-quit', () => { if (!completed) app.exit(1) })
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-theme-preview-'))
fs.chmodSync(fixture, 0o700)
app.setPath('userData', path.join(fixture, 'profile'))
const evidence = path.join(fixture, 'evidence')
fs.mkdirSync(evidence, { mode: 0o700 })
const timeout = setTimeout(() => app.exit(2), 45000)
let server

async function main() {
  try {
    await app.whenReady()
    const { previewTheme } = await import('../dist/electron/theme-preview.mjs')
    const { ThemeRevisions } = await import('../dist/electron/theme-revisions.mjs')
    const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
    const source = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim()
    assert.match(source, /^[a-f0-9]{40}$/)
    const dirty = Boolean(execFileSync('git', ['status', '--porcelain'], { cwd: repo, encoding: 'utf8' }).trim())
    const base = JSON.parse(fs.readFileSync(path.join(repo, 'linux/themes/herald-ocean/theme.json'), 'utf8'))
    delete base.shell
    const store = new ThemeRevisions(path.join(fixture, '.config/herald-os/theme-versions'), fixture)
    let received = 0
    server = http.createServer((_request, response) => { received++; response.end('isolated network canary') })
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
    const address = `http://127.0.0.1:${server.address().port}/preview-canary`
    let boundary
    app.once('web-contents-created', (_event, contents) => {
      contents.once('did-finish-load', () => {
        boundary = contents.executeJavaScript(`(async()=>({networkDenied:await fetch(${JSON.stringify(address)}).then(()=>false,()=>true),scripts:document.querySelectorAll('script').length,images:document.querySelectorAll('img').length,node:typeof process,require:typeof require}))()`)
      })
    })
    const first = store.publish({ ...base, name: 'preview-safe-design', label: `<img src="${address}" onerror="alert(1)">` })
    const good = await previewTheme(first)
    assert.equal(good.passed, true)
    assert.deepEqual(await boundary, { networkDenied: true, scripts: 0, images: 0, node: 'undefined', require: 'undefined' })
    assert.equal(received, 0)
    const cases = [{ name: 'safe-escaped-label', result: good }]

    const bitmap = Buffer.alloc(16 * 16 * 4)
    for (let index = 0; index < bitmap.length; index += 4) { bitmap[index] = 128; bitmap[index + 1] = 68; bitmap[index + 2] = 20; bitmap[index + 3] = 255 }
    const raster = nativeImage.createFromBitmap(bitmap, { width: 16, height: 16, scaleFactor: 1 }).toPNG()
    const withImage = store.publish({ ...base, name: 'preview-raster-design', wallpaper: 'wallpaper.png' }, raster)
    const renderedImage = await previewTheme(withImage)
    assert.equal(renderedImage.passed, true)
    assert.equal(renderedImage.checks.rasterDecoded, true)
    cases.push({ name: 'actual-raster-decoded', result: renderedImage })

    const badContrast = store.publish({ ...base, name: 'preview-unreadable-design', colors: { ...base.colors, fg: base.colors.bg } })
    const unreadable = await previewTheme(badContrast)
    assert.equal(unreadable.passed, false)
    assert.equal(unreadable.checks.textContrast, false)
    cases.push({ name: 'unreadable-update-rejected', result: unreadable })

    // This foreground is readable on the body but disappears on the real glass
    // card. Contrast must use the actual composed surface, not just theme.bg.
    const badSurface = store.publish({ ...base, name: 'preview-unreadable-surface',
      colors: { ...base.colors, bg: '#000000', fg: '#aaaaaa', surface: '#ffffff', accent: '#ffffff' } })
    const surface = await previewTheme(badSurface, true)
    assert.equal(surface.passed, false)
    assert.equal(surface.checks.textContrast, false)
    cases.push({ name: 'unreadable-glass-surface-rejected', result: surface })

    const badImage = store.publish({ ...base, name: 'preview-corrupt-image', wallpaper: 'wallpaper.png' }, Buffer.from('not a raster image'))
    const undecodable = await previewTheme(badImage)
    assert.equal(undecodable.passed, false)
    assert.equal(undecodable.checks.rasterDecoded, false)
    cases.push({ name: 'corrupt-raster-rejected', result: undecodable })
    assert.equal(store.read(first.spec.name, first.revision).revision, first.revision)
    assert.equal(received, 0)

    const proofs = cases.map(({ name, result }) => {
      const png = Buffer.from(result.png.split(',')[1], 'base64')
      assert.equal(createHash('sha256').update(png).digest('hex'), result.screenshotSha256)
      fs.writeFileSync(path.join(evidence, `${name}.png`), png, { flag: 'wx', mode: 0o600 })
      const { png: _privateImage, ...proof } = result
      return { case: name, ...proof }
    })
    const report = { source_commit: source, work_tree_dirty: dirty, electron: process.versions.electron,
      chromium: process.versions.chrome, actual_renderer: true, network_canary_requests: received, cases: proofs }
    fs.writeFileSync(path.join(evidence, 'theme-preview.json'), JSON.stringify(report, null, 2), { flag: 'wx', mode: 0o600 })
    if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `evidence=${evidence}\n`)
    console.log(JSON.stringify({ evidence, source_commit: source, work_tree_dirty: dirty,
      actual_renderer: true, cases: proofs.map(proof => ({ case: proof.case, passed: proof.passed, checks: proof.checks })) }))
    clearTimeout(timeout)
    await new Promise(resolve => server.close(resolve))
    completed = true
    app.quit()
  } catch (error) {
    // Never emit data URLs, image bytes, renderer HTML or application/profile state.
    console.error('Actual isolated theme preview gate failed:', error instanceof assert.AssertionError ? error.message : error.name)
    clearTimeout(timeout)
    server?.close()
    app.exit(1)
  }
}

void main()
