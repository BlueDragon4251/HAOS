/** Real controller sockets + native production broker, explicit offline session fixture. */
import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { app } from 'electron'

assert.equal(process.env.HAOS_DISPOSABLE_SCREEN_TEST, '1')
assert.notEqual(process.getuid(), 0)
app.enableSandbox()
app.on('window-all-closed', () => {})
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-gui-integration-'))
fs.chmodSync(root, 0o700)
app.setPath('userData', path.join(root, 'profile'))
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
process.env.HAOS_BACKEND_CONFIG = '/etc/haos/backend.json'
let child, native, stage = 'startup'
const mark = value => { stage = value; fs.writeSync(2, `HAOS_GUI_FIXTURE_PHASE ${value}\n`) }
const deadline = setTimeout(() => { native?.stop(); child?.kill('SIGKILL'); app.exit(2) }, 60000)

function request(socket, method, params) {
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
      if (size > 131072) return finish(new Error('Fixture response bound'))
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
    const wait = async operation => {
      const until = Date.now() + 12000
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
        const receipt = await request('gui.sock', 'gui.result', { session, id })
        return ['succeeded', 'failed', 'uncertain'].includes(receipt.state) ? receipt : null
      })
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
    await stopController()
    const evidence = path.join(root, 'evidence')
    fs.mkdirSync(evidence, { mode: 0o700 })
    const report = { source_commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
      work_tree_dirty: Boolean(execFileSync('git', ['status', '--porcelain'], { cwd: repo, encoding: 'utf8' }).trim()),
      actual_native_socket_pipeline: true, session_is_explicit_fixture: true, real_model_turn: false, installed_system: false,
      checks: { actual_input_and_inspection: true, actual_capture: true, actual_read_without_body_persistence: true, private_bodies_absent_from_audit: true, unauthorized_methods_denied: true,
        lost_ack_not_reexecuted: true, controller_restart_blocks_mission: true, durable_audit_survives: true, actual_fragmented_readiness_framed: true } }
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
