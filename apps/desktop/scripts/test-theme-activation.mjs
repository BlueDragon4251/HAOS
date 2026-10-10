/** Actual saved revisions -> preview -> fixed Linux outputs -> renderer -> independent rollback. */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { app, BrowserWindow, session } from 'electron'

assert.equal(process.env.HAOS_DISPOSABLE_SCREEN_TEST, '1')
assert.notEqual(process.getuid(), 0)
assert.equal(process.env.WAYLAND_DISPLAY, 'haos-disposable-wayland')
assert.equal(path.basename(path.dirname(process.env.XDG_RUNTIME_DIR || '')).startsWith('haos-wayland-gate-'), true)
app.enableSandbox()
app.on('window-all-closed', () => {})
let completed = false
app.on('before-quit', () => { if (!completed) { fs.writeSync(2, 'HAOS_THEME_FIXTURE_PHASE premature-quit\n'); app.exit(1) } })
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-theme-activation-'))
fs.chmodSync(fixture, 0o700)
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
process.env.HOME = fixture
process.env.HERMES_HOME = path.join(fixture, '.hermes')
process.env.HERALD_OS_THEMES = path.join(repo, 'linux/themes')
process.env.PATH = path.join(repo, 'linux/bin') + ':' + process.env.PATH
app.setPath('userData', path.join(fixture, 'profile'))
const evidence = path.join(fixture, 'evidence')
fs.mkdirSync(evidence, { mode: 0o700 })
const timeout = setTimeout(() => app.exit(2), 60000)
const journal = path.join(fixture, '.config/herald-os/theme-activation/state.json')
const preferences = path.join(fixture, '.hermes/herald-os/prefs.json')
let win

async function main() {
  try {
    fs.writeSync(2, 'HAOS_THEME_FIXTURE_PHASE ready\n')
    await app.whenReady()
    fs.writeSync(2, 'HAOS_THEME_FIXTURE_PHASE imports\n')
    const { ThemeRevisions } = await import('../dist/electron/theme-revisions.mjs')
    const { applyTheme } = await import('../dist/electron/theme-activation.mjs')
    const { verifyThemeShell } = await import('../dist/electron/theme-health.mjs')
    const base = JSON.parse(fs.readFileSync(path.join(repo, 'linux/themes/herald-ocean/theme.json'), 'utf8'))
    delete base.shell
    const store = new ThemeRevisions(path.join(fixture, '.config/herald-os/theme-versions'), fixture)
    const first = store.publish({ ...base, name: 'activation-design' })
    const second = store.publish({ ...base, name: 'activation-design', colors: { ...base.colors, accent: '#a7bfff' }, description: 'A different actual revision' })
    const cssDir = path.join(repo, 'apps/desktop/dist/renderer/assets')
    const cssFile = fs.readdirSync(cssDir).filter(name => /^index-[\w-]+\.css$/.test(name))
    assert.equal(cssFile.length, 1)
    const css = fs.readFileSync(path.join(cssDir, cssFile[0]), 'utf8')
    const documentCode = fs.readFileSync(path.join(repo, 'apps/desktop/dist/electron/theme-document.js'), 'utf8')
    assert.equal(/<\/script/i.test(documentCode), false)
    const isolated = session.fromPartition('haos-theme-activation-fixture-' + process.pid)
    isolated.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
    isolated.setPermissionCheckHandler(() => false)
    isolated.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*', 'file://*/*', 'ws://*/*', 'wss://*/*'] }, (_details, callback) => callback({ cancel: true }))
    isolated.on('will-download', event => event.preventDefault())
    fs.writeSync(2, 'HAOS_THEME_FIXTURE_PHASE window\n')
    win = new BrowserWindow({ width: 960, height: 640, show: false, frame: false, title: 'HAOS Theme activation fixture',
      webPreferences: { session: isolated, sandbox: true, contextIsolation: true, nodeIntegration: false } })
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    const html = `<html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-fixture'; connect-src 'none'; img-src data:"><style>${css}</style></head><body style="width:960px;height:640px"><main class="p-8"><h1>Explicit theme activation fixture</h1><button>Recovery remains available</button></main><script nonce="fixture">window.heraldOS={shell:{mode:'panels'}};${documentCode}</script></body></html>`
    await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html))
    win.showInactive()
    fs.writeSync(2, 'HAOS_THEME_FIXTURE_PHASE activate\n')
    const checks = {}
    let hiddenRevision
    let applying = Promise.resolve()
    const deps = { panels: true,
      // No model/provider/session is started or represented by this fixture.
      backend: { getState: () => ({ phase: 'idle' }) },
      broadcast: next => {
        applying = applying.then(() => win.webContents.executeJavaScript(`HeraldThemeDocument.applyPrefsToDocument(${JSON.stringify(next)}); document.body.style.visibility=${JSON.stringify(next.themeRevision === hiddenRevision ? 'hidden' : 'visible')}`))
      },
      verify: async next => { await applying; return verifyThemeShell([win], next) }
    }
    const accepted = await applyTheme(first.spec.name, deps, first.revision)
    fs.writeSync(2, 'HAOS_THEME_FIXTURE_PHASE healthy\n')
    assert.equal(accepted.themeRevision, first.revision)
    assert.equal(JSON.parse(fs.readFileSync(journal, 'utf8')).status, 'committed')
    checks.actual_preview_and_renderer_confirmed = true
    checks.actual_fixed_linux_outputs = fs.readFileSync(path.join(fixture, '.config/niri/theme.kdl'), 'utf8').includes('active-color')
    assert.equal(checks.actual_fixed_linux_outputs, true)
    const oldNiri = fs.readFileSync(path.join(fixture, '.config/niri/theme.kdl'))
    const oldFoot = fs.readFileSync(path.join(fixture, '.config/foot/foot.ini'))
    hiddenRevision = second.revision
    await assert.rejects(applyTheme(second.spec.name, deps, second.revision), /actual shell did not verify/)
    fs.writeSync(2, 'HAOS_THEME_FIXTURE_PHASE rollback\n')
    await applying
    assert.equal(JSON.parse(fs.readFileSync(journal, 'utf8')).status, 'rolled_back')
    assert.equal(JSON.parse(fs.readFileSync(preferences, 'utf8')).themeRevision, first.revision)
    assert.deepEqual(fs.readFileSync(path.join(fixture, '.config/niri/theme.kdl')), oldNiri)
    assert.deepEqual(fs.readFileSync(path.join(fixture, '.config/foot/foot.ini')), oldFoot)
    checks.actual_unusable_renderer_rolls_back = true
    assert.equal(await verifyThemeShell([win], accepted), true)
    checks.prior_renderer_restored = true
    const rejected = store.publish({ ...base, name: 'activation-unreadable', colors: { ...base.colors, fg: base.colors.bg } })
    await assert.rejects(applyTheme(rejected.spec.name, deps, rejected.revision), /preview failed/)
    assert.equal(JSON.parse(fs.readFileSync(preferences, 'utf8')).themeRevision, first.revision)
    checks.unreadable_draft_never_activates = true
    assert.equal(await verifyThemeShell([], accepted), false)
    assert.equal(await verifyThemeShell([win], { ...accepted, accent: 'violet' }), false)
    checks.missing_or_wrong_shell_denied = true
    assert.equal(await win.webContents.executeJavaScript('typeof process'), 'undefined')
    checks.renderer_remains_sandboxed = true
    const report = { source_commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
      work_tree_dirty: Boolean(execFileSync('git', ['status', '--porcelain'], { cwd: repo, encoding: 'utf8' }).trim()),
      actual_renderer: true, actual_theme_engine: true, independent_watchdog: true,
      installed_niri: false, full_desktop_acceptance: false, real_model_turn: false, checks }
    fs.writeFileSync(path.join(evidence, 'theme-activation.json'), JSON.stringify(report, null, 2), { flag: 'wx', mode: 0o600 })
    if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `evidence=${evidence}\n`)
    console.log(JSON.stringify({ evidence, ...report }))
    clearTimeout(timeout)
    win.destroy()
    completed = true
    app.quit()
  } catch (error) {
    // No preference bodies, HTML, screenshots, sessions or full journal in logs.
    const known = new Set(['Actual shell verification is unavailable', 'The theme engine could not start a verified activation; inspect its private recovery state',
      'Isolated theme preview failed; the current theme was not changed',
      'Invalid theme activation receipt', 'The actual shell did not verify the tested theme', 'Theme activation could not be confirmed',
      'Theme recovery preserved a conflict; inspect the private activation journal', 'Theme preview failed its readability, raster or isolation checks; the previous theme remains in use'])
    fs.writeSync(2, 'Actual theme activation gate failed: ' + (error instanceof assert.AssertionError ? error.message.slice(0, 500)
      : known.has(error.message) ? error.message : error.name) + '\n')
    clearTimeout(timeout)
    app.exit(1)
  }
}
void main()
