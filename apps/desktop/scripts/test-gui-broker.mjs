/** Real Chromium/native-input gate, using only disposable documents and canaries. */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { app, BrowserWindow, clipboard, nativeImage } from 'electron'

assert.equal(process.env.HAOS_DISPOSABLE_SCREEN_TEST, '1')
assert.notEqual(process.getuid(), 0)
app.enableSandbox()
app.on('window-all-closed', () => {})
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-gui-broker-'))
fs.chmodSync(fixture, 0o700)
app.setPath('userData', path.join(fixture, 'profile'))
const evidence = path.join(fixture, 'evidence')
fs.mkdirSync(evidence, { mode: 0o700 })
const deadline = setTimeout(() => app.exit(2), 45000)
let browser, server

async function main() {
  try {
    await app.whenReady()
    const { MissionBrowser } = await import('../dist/electron/gui-broker.mjs')
    browser = new MissionBrowser(true)
    const mission = randomUUID()
    const execute = action => browser.execute({ id: randomUUID(), mission, action })
    let received = 0
    server = http.createServer((_request, response) => { received++; response.end('GUI network canary') })
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
    const address = `http://127.0.0.1:${server.address().port}/private-canary`
    const html = `<style>body{margin:0;background:#fff}input{display:block;height:36px;width:300px;margin:10px}#marker{width:80px;height:80px;background:#00cc44}</style><input id="first"><input id="second"><input id="files" type="file"><div id="marker"></div><script>document.body.innerHTML='UNAUTHORIZED SCRIPT';fetch('${address}');new RTCPeerConnection({iceServers:[{urls:'stun:127.0.0.1:12345'}]});alert('Owner dialog');</script><img src="${address}"><a href="file:///etc/shadow">private file</a>`
    const opened = await execute({ operation: 'open', html })
    const window = opened.window
    assert.deepEqual(await execute({ operation: 'state' }), { windows: [opened] })
    const win = BrowserWindow.getAllWindows()[0]
    assert.equal(win.isFocusable(), false)
    const rendererPids = new Set([win.webContents.getOSProcessId(), ...win.webContents.mainFrame.frames.map(frame => frame.osProcessId)])
    assert(rendererPids.size >= 2, 'opaque mission document must use a separate renderer')
    for (const pid of rendererPids) {
      assert(Number.isInteger(pid) && pid > 0)
      const status = fs.readFileSync(`/proc/${pid}/status`, 'utf8')
      assert.match(status, /^NoNewPrivs:\s*1$/m)
      assert.match(status, /^Seccomp:\s*2$/m)
      assert.match(status, /^CapEff:\s*0+$/m)
    }
    const prefs = win.webContents.getLastWebPreferences()
    assert.equal(prefs.sandbox, true)
    assert.equal(prefs.nodeIntegration, false)
    assert.equal(prefs.javascript, false)
    assert.equal(prefs.preload, undefined)
    let choosers = 0
    win.webContents.debugger.on('message', (_event, method) => { if (method === 'Page.fileChooserOpened') choosers++ })
    const first = await execute({ operation: 'capture', window })
    await execute({ operation: 'click', window, x: 80, y: 70 })
    await execute({ operation: 'type', window, text: 'Real GUI input 4251' })
    await execute({ operation: 'key', window, key: 'Tab' })
    await execute({ operation: 'type', window, text: 'Second actual field' })
    const inspected = await execute({ operation: 'inspect', window })
    assert.equal(inspected.fields.find(field => field.name === 'first').value, 'Real GUI input 4251')
    assert.equal(inspected.fields.find(field => field.name === 'second').value, 'Second actual field')
    assert.equal(inspected.fields.find(field => field.name === 'files').value, '[redacted]')
    assert.equal(received, 0)
    const typed = await execute({ operation: 'capture', window })
    assert.notEqual(typed.jpeg, first.jpeg)
    const image = nativeImage.createFromBuffer(Buffer.from(typed.jpeg, 'base64'))
    assert.deepEqual(image.getSize(), { width: 800, height: 600 })
    // Inspect actual rendered marker pixels, not only the returned dimensions.
    const bitmap = image.toBitmap()
    const offset = (240 * 800 + 40) * 4
    assert(bitmap[offset + 1] > bitmap[offset + 2] + 100)
    await clipboard.writeText('DISPOSABLE OWNER CLIPBOARD CANARY')
    await assert.rejects(execute({ operation: 'key', window, key: 'Control+V' }))
    assert.equal(await clipboard.readText(), 'DISPOSABLE OWNER CLIPBOARD CANARY')
    await clipboard.clear()
    await execute({ operation: 'click', window, x: 80, y: 170 })
    await new Promise(resolve => setTimeout(resolve, 100))
    assert(choosers > 0, 'actual chooser request must be intercepted before host dialog')
    await assert.rejects(browser.execute({ id: randomUUID(), mission: randomUUID(), action: { operation: 'capture', window } }))
    await assert.rejects(execute({ operation: 'capture', window: randomUUID() }))
    await assert.rejects(execute({ operation: 'inspect', window: randomUUID() }))
    await assert.rejects(execute({ operation: 'open', html: 'second browser' }))
    await assert.rejects(execute({ operation: 'click', window, x: 10, y: 10 }))
    await assert.rejects(execute({ operation: 'type', window, text: '\u0001' }))
    await assert.rejects(execute({ operation: 'open', html: 'report', url: address }))
    await assert.rejects(execute({ operation: 'open', html: '<iframe srcdoc="owner"></iframe>' }))
    assert.equal(received, 0)
    await execute({ operation: 'focus', window })
    await execute({ operation: 'close', window })
    assert.deepEqual(await execute({ operation: 'state' }), { windows: [] })
    await assert.rejects(execute({ operation: 'capture', window }))
    const another = await execute({ operation: 'open', html: '<p>New real window</p>' })
    browser.retain(null)
    await assert.rejects(execute({ operation: 'capture', window: another.window }))
    const privateFields = await execute({ operation: 'open', html: '<input id="secret" type="password" value="DISPOSABLE_FORM_SECRET"><textarea id="notes">Real text area</textarea>' })
    const privateInspection = await execute({ operation: 'inspect', window: privateFields.window })
    assert.equal(privateInspection.fields.find(field => field.name === 'secret').value, '[redacted]')
    assert.equal(privateInspection.fields.find(field => field.name === 'notes').value, 'Real text area')
    assert.equal(JSON.stringify(privateInspection).includes('DISPOSABLE_FORM_SECRET'), false)
    browser.retain(null)
    const source = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
    const report = { source_commit: source, work_tree_dirty: Boolean(execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim()), electron: process.versions.electron,
      chromium: process.versions.chrome, actual_renderer: true, model_turn: false, installed_wayland: false,
      checks: { typed_actual_fields: true, captured_actual_pixels: true, renderer_sandbox: true, no_caller_scripts: true,
        network_canary_denied: received === 0, chooser_intercepted: choosers > 0, clipboard_shortcut_denied: true,
        mission_and_window_denials: true, closed_window_denied: true, mission_cleanup: true, actual_form_inspection: true, sensitive_fields_masked: true },
      capture_sha256: createHash('sha256').update(Buffer.from(typed.jpeg, 'base64')).digest('hex') }
    fs.writeFileSync(path.join(evidence, 'gui-broker.json'), JSON.stringify(report, null, 2), { mode: 0o600, flag: 'wx' })
    fs.writeFileSync(path.join(evidence, 'disposable-form.jpg'), Buffer.from(typed.jpeg, 'base64'), { mode: 0o600, flag: 'wx' })
    if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `evidence=${evidence}\n`)
    console.log(JSON.stringify({ evidence, ...report }))
    clearTimeout(deadline)
    await new Promise(resolve => server.close(resolve))
    app.quit()
  } catch (error) {
    browser?.retain(null)
    clearTimeout(deadline)
    server?.close()
    console.error('Actual GUI capability gate failed:', error instanceof assert.AssertionError ? error.message : error.name)
    app.exit(1)
  }
}
void main()
