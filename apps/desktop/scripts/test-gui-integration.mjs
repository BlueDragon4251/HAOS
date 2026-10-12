/** Real controller sockets + native production broker, explicit offline session fixture. */
import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { app, BrowserWindow, session as electronSession } from 'electron'

assert.equal(process.env.HAOS_DISPOSABLE_SCREEN_TEST, '1')
assert.notEqual(process.getuid(), 0)
app.enableSandbox()
app.on('window-all-closed', () => {})
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-gui-integration-'))
fs.chmodSync(root, 0o700)
app.setPath('userData', path.join(root, 'profile'))
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
process.env.HAOS_BACKEND_CONFIG = '/etc/haos/backend.json'
process.env.HOME = root
process.env.HERMES_HOME = path.join(root, '.hermes')
process.env.HERALD_OS_THEMES = path.join(repo, 'linux/themes')
process.env.PATH = path.join(repo, 'linux/bin') + ':' + process.env.PATH
let child, native, shell, stage = 'startup'
const mark = value => { stage = value; fs.writeSync(2, `HAOS_GUI_FIXTURE_PHASE ${value}\n`) }
const deadline = setTimeout(() => { native?.stop(); child?.kill('SIGKILL'); app.exit(2) }, 60000)

function request(socket, method, params, responseLimit = 131072) {
  return new Promise((resolve, reject) => {
    const connection = net.createConnection(path.join(root, socket))
    const chunks = []
    let size = 0, settled = false
    const finish = (error, value) => { if (settled) return; settled = true; connection.destroy(); error ? reject(error) : resolve(value) }
    connection.setTimeout(5000, () => finish(new Error('Fixture socket deadline')))
    connection.on('error', error => finish(error))
    connection.on('end', () => finish(new Error('Incomplete fixture reply')))
    connection.on('connect', () => connection.write(JSON.stringify({ method, params }) + '\n'))
    connection.on('data', data => {
      size += data.length
      if (size > responseLimit) return finish(new Error('Fixture response bound'))
      chunks.push(data)
      if (!data.includes(10)) return
      const reply = JSON.parse(Buffer.concat(chunks).toString().split('\n')[0])
      finish(reply.ok ? null : new Error('Fixture action denied'), reply.result)
    })
  })
}

async function startController() {
  child = spawn('python3', [path.join(repo, 'linux/haos/runtime/probe_gui_controller.py'), root], {
    env: { PATH: process.env.PATH, LANG: 'C.UTF-8', PYTHONDONTWRITEBYTECODE: '1', HAOS_DISPOSABLE_SCREEN_TEST: '1', HAOS_DISPOSABLE_SPLIT_READY: '1' }, stdio: ['pipe', 'pipe', 'pipe']
  })
  // Fixture stdout contains only readiness/scalar receipts; no inherited env/secrets.
  return await new Promise((resolve, reject) => {
    let output = ''
    let fragmentAcknowledged = false
    const timer = setTimeout(() => reject(new Error('Controller readiness deadline')), 10000)
    child.once('exit', () => { clearTimeout(timer); reject(new Error('Controller fixture exited')) })
    child.stdout.on('data', data => {
      output += data.toString()
      if (output.length > 16384) return reject(new Error('Readiness limit'))
      if (!fragmentAcknowledged && output.startsWith('{"ready"') && !output.includes('\n')) {
        fragmentAcknowledged = true
        child.stdin.write('R')
      }
      const line = output.split('\n').slice(0, -1).find(item => item.startsWith('{"ready"'))
      if (line) { clearTimeout(timer); assert(fragmentAcknowledged); resolve(JSON.parse(line)) }
    })
  })
}

async function stopController() {
  if (!child || child.exitCode !== null || child.signalCode !== null) return
  const done = new Promise(resolve => child.once('exit', resolve))
  child.kill('SIGTERM')
  const timer = setTimeout(() => child.kill('SIGKILL'), 3000)
  await done
  clearTimeout(timer)
}

async function main() {
  try {
    await app.whenReady()
    const { NativeGuiBroker } = await import('../dist/electron/gui-broker.mjs')
    mark('controller-start')
    const ready = await startController()
    assert.equal(ready.real_model_turn, false)
    let dropAck = false
    const transport = async (method, params) => {
      if (method === 'gui.ack' && dropAck) { dropAck = false; throw new Error('Injected acknowledgement loss') }
      return request('control.sock', method, params)
    }
    native = new NativeGuiBroker(transport)
    native.start()
    const session = ready.fixture_session
    const wait = async (operation, bound = 12000) => {
      const until = Date.now() + bound
      while (Date.now() < until) {
        const result = await operation()
        if (result) return result
        await new Promise(resolve => setTimeout(resolve, 100))
      }
      throw new Error('Integrated GUI receipt deadline')
    }
    mark('native-attach')
    await wait(async () => {
      try { return await request('gui.sock', 'gui.submit', { session, id: randomUUID(), action: { operation: 'state' } }) }
      catch { return null }
    })
    const submit = async (action, id = randomUUID()) => {
      await request('gui.sock', 'gui.submit', { session, id, action })
      return await wait(async () => {
        const receipt = await request('gui.sock', 'gui.result', { session, id }, action.operation === 'theme.preview' ? 1500000 : 131072)
        return ['succeeded', 'failed', 'uncertain'].includes(receipt.state) ? receipt : null
      }, action.operation === 'theme.apply' ? 48000 : action.operation === 'theme.preview' ? 23000 : 12000)
    }
    mark('open')
    const opened = await submit({ operation: 'open', html: '<input id="field" style="margin:0;width:300px;height:40px"><p>Integrated private visible report</p>' })
    assert.equal(opened.state, 'succeeded')
    const window = opened.result.window
    mark('click')
    assert.equal((await submit({ operation: 'click', window, x: 40, y: 70 })).state, 'succeeded')
    mark('type')
    assert.equal((await submit({ operation: 'type', window, text: 'Integrated real native input' })).state, 'succeeded')
    mark('inspect')
    const inspected = await submit({ operation: 'inspect', window })
    assert.equal(inspected.state, 'succeeded')
    mark('verify-input')
    assert.equal(inspected.result.fields[0].value, 'Integrated real native input')
    mark('capture')
    const captured = await submit({ operation: 'capture', window })
    assert.equal(captured.state, 'succeeded')
    assert(Buffer.from(captured.result.jpeg, 'base64').length > 1000)
    mark('read-visible-text')
    const read = await submit({ operation: 'read', window })
    assert.equal(read.state, 'succeeded')
    assert.match(read.result.text, /Integrated private visible report/)
    assert.doesNotMatch(read.result.text, /Integrated real native input/)
    mark('audit-and-denials')
    const events = await request('control.sock', 'missions.events', { id: ready.mission })
    assert(events.some(event => event.kind === 'gui.succeeded'))
    assert.equal(JSON.stringify(events).includes('Integrated real native input'), false)
    assert.equal(JSON.stringify(events).includes(captured.result.jpeg), false)
    assert.equal(JSON.stringify(events).includes('Integrated private visible report'), false)
    mark('mission-theme-schema')
    const schema = await submit({ operation: 'theme.sdk' })
    assert.equal(schema.state, 'succeeded'); assert.equal(schema.result.executable_extensions, false)
    const theme = JSON.parse(fs.readFileSync(path.join(repo, 'linux/themes/herald-ocean/theme.json'), 'utf8'))
    mark('mission-theme-stage')
    const saved = await submit({ operation: 'theme.stage', theme: { colors: theme.colors, label: 'Actual queued data theme' } })
    assert.equal(saved.state, 'succeeded'); assert.equal(saved.result.name, 'haos-t-' + ready.mission.replaceAll('-', ''))
    mark('mission-theme-preview')
    const preview = await submit({ operation: 'theme.preview', revision: saved.result.revision })
    assert.equal(preview.state, 'succeeded'); assert.equal(preview.result.passed, true)
    assert(Buffer.from(preview.result.base64, 'base64').length > 1000)
    const themeEvents = await request('control.sock', 'missions.events', { id: ready.mission })
    assert.equal(JSON.stringify(themeEvents).includes(preview.result.base64), false)
    await assert.rejects(request('gui.sock', 'gui.lease', { id: randomUUID(), epoch: randomUUID() }))
    mark('mission-theme-unsupported-apply')
    const unsupported = await submit({ operation: 'theme.apply', revision: saved.result.revision })
    assert.equal(unsupported.state, 'failed')
    assert.equal(fs.existsSync(path.join(root, '.hermes/herald-os/prefs.json')), false)
    mark('mission-theme-actual-shell')
    const { verifyThemeShell } = await import('../dist/electron/theme-health.mjs')
    const cssDir = path.join(repo, 'apps/desktop/dist/renderer/assets')
    const cssFiles = fs.readdirSync(cssDir).filter(name => /^index-[\w-]+\.css$/.test(name))
    assert.equal(cssFiles.length, 1)
    const css = fs.readFileSync(path.join(cssDir, cssFiles[0]), 'utf8')
    const documentCode = fs.readFileSync(path.join(repo, 'apps/desktop/dist/electron/theme-document.js'), 'utf8')
    assert.equal(/<\/script/i.test(documentCode), false)
    const isolated = electronSession.fromPartition('haos-queued-theme-' + process.pid)
    isolated.setPermissionRequestHandler((_wc, _permission, reply) => reply(false))
    isolated.setPermissionCheckHandler(() => false)
    isolated.on('will-download', event => event.preventDefault())
    isolated.webRequest.onBeforeRequest({ urls: ['http://*/*','https://*/*','file://*/*','ws://*/*','wss://*/*'] }, (_details, reply) => reply({ cancel: true }))
    shell = new BrowserWindow({ width: 960, height: 640, show: false, frame: false, title: 'HAOS queued theme shell fixture',
      webPreferences: { session: isolated, sandbox: true, contextIsolation: true, nodeIntegration: false } })
    shell.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    await shell.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(`<html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-fixture'; img-src data:; connect-src 'none'"><style>${css}</style></head><body style="width:960px;height:640px"><h1>Explicit queued theme fixture</h1><button>Actual tested shell control</button><script nonce="fixture">window.heraldOS={shell:{mode:'panels'}};${documentCode}</script></body></html>`))
    shell.showInactive()
    let applying = Promise.resolve(), hiddenRevision
    native.configureThemes({ panels: true, backend: { getState: () => ({ phase: 'idle' }) },
      broadcast: prefs => { applying = applying.then(() => shell.webContents.executeJavaScript(`HeraldThemeDocument.applyPrefsToDocument(${JSON.stringify(prefs)}); document.body.style.visibility=${JSON.stringify(prefs.themeRevision === hiddenRevision ? 'hidden' : 'visible')}`)) },
      verify: async prefs => { await applying; return verifyThemeShell([shell], prefs) }
    })
    mark('mission-theme-actual-apply')
    const applied = await submit({ operation: 'theme.apply', revision: saved.result.revision })
    assert.equal(applied.state, 'succeeded'); assert.equal(applied.result.verified, true)
    const preferences = path.join(root, '.hermes/herald-os/prefs.json')
    assert.equal(JSON.parse(fs.readFileSync(preferences, 'utf8')).themeRevision, saved.result.revision)
    const broken = await submit({ operation: 'theme.stage', theme: { colors: { ...theme.colors, accent: '#a7bfff' }, label: 'Actual queued broken renderer update' } })
    hiddenRevision = broken.result.revision
    mark('mission-theme-actual-rollback')
    const failed = await submit({ operation: 'theme.apply', revision: hiddenRevision })
    assert.equal(failed.state, 'failed')
    assert.equal(JSON.parse(fs.readFileSync(path.join(root, '.config/herald-os/theme-activation/state.json'), 'utf8')).status, 'rolled_back')
    assert.equal(JSON.parse(fs.readFileSync(preferences, 'utf8')).themeRevision, saved.result.revision)
    await applying
    assert.equal(await shell.webContents.executeJavaScript('getComputedStyle(document.body).visibility'), 'visible')
    await assert.rejects(request('gui.sock', 'missions.create', { goal: 'owner', idempotency_key: 'attack' }))
    await assert.rejects(request('gui.sock', 'gui.submit', { session: 'forged', id: randomUUID(), action: { operation: 'state' } }))
    const lostId = randomUUID(), captureAction = { operation: 'capture', window }
    mark('lost-ack')
    dropAck = true
    const lost = await submit(captureAction, lostId)
    assert.equal(lost.state, 'uncertain')
    const retry = await request('gui.sock', 'gui.submit', { session, id: lostId, action: captureAction })
    assert.equal(retry.state, 'uncertain')
    mark('controller-restart')
    await stopController()
    const restarted = await startController()
    mark('restart-ready')
    assert.equal(restarted.mission, ready.mission)
    assert.equal(restarted.state, 'blocked')
    const persisted = await request('control.sock', 'missions.events', { id: ready.mission })
    assert(persisted.some(event => event.kind === 'gui.uncertain' && event.payload.id === lostId))
    await assert.rejects(request('gui.sock', 'gui.submit', { session, id: randomUUID(), action: { operation: 'state' } }))
    mark('cleanup')
    native.stop()
    shell.destroy()
    await stopController()
    const evidence = path.join(root, 'evidence')
    fs.mkdirSync(evidence, { mode: 0o700 })
    const report = { source_commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
      work_tree_dirty: Boolean(execFileSync('git', ['status', '--porcelain'], { cwd: repo, encoding: 'utf8' }).trim()),
      actual_native_socket_pipeline: true, session_is_explicit_fixture: true, real_model_turn: false, installed_system: false,
      checks: { actual_input_and_inspection: true, actual_capture: true, actual_read_without_body_persistence: true, private_bodies_absent_from_audit: true, unauthorized_methods_denied: true,
        lost_ack_not_reexecuted: true, controller_restart_blocks_mission: true, durable_audit_survives: true, actual_fragmented_readiness_framed: true,
        real_queue_mission_theme_schema_and_revision: true, real_queue_theme_preview_and_private_pixels: true,
        agent_native_lease_and_unsupported_activation_denied: true, real_queue_guarded_theme_activation_and_shell_verified: true,
        real_queue_broken_renderer_update_rolls_back: true } }
    fs.writeFileSync(path.join(evidence, 'gui-integration.json'), JSON.stringify(report, null, 2), { flag: 'wx', mode: 0o600 })
    if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, `evidence=${evidence}\n`)
    console.log(JSON.stringify({ evidence, ...report }))
    clearTimeout(deadline)
    app.quit()
  } catch (error) {
    fs.writeSync(2, `Actual native/socket GUI gate failed: ${stage} ${error.name}\n`)
    if (error instanceof assert.AssertionError) {
      const length = value => typeof value === 'string' ? value.length : -1
      fs.writeSync(2, `Actual native/socket GUI assertion lengths: ${length(error.actual)} ${length(error.expected)}\n`)
    }
    native?.stop()
    await stopController()
    clearTimeout(deadline)
    // Electron app.exit can terminate an asynchronous console write. Preserve
    // the fixed phase/error class synchronously, never bodies or session values.
    app.exit(1)
  }
}
void main()
