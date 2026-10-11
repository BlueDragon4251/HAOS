import { afterEach, describe, expect, it } from 'vitest'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { MissionCompositor } from './niri.ts'

const title = 'HAOS Mission fixed-broker-title Window fixed-broker-window'
const cleanup: (() => void)[] = []
afterEach(() => { for (const close of cleanup.splice(0)) close() })

async function fixture(alter?: (request: unknown, reply: unknown) => unknown) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'haos-niri-ipc-'))
  fs.chmodSync(root, 0o700)
  const endpoint = path.join(root, 'niri.sock'), requests: unknown[] = []
  let workspace = 10
  const server = net.createServer(socket => {
    let input = ''
    socket.on('data', chunk => {
      input += chunk.toString()
      if (!input.includes('\n')) return
      const request = JSON.parse(input.split('\n')[0]); requests.push(request)
      let reply: unknown
      if (request === 'Windows') reply = { Ok: { Windows: [{ id: 12, pid: process.pid, title, workspace_id: workspace, is_focused: false, layout: { window_size: [800, 600] } }, { id: 99, pid: process.pid, title: 'Owner private window', workspace_id: 10, is_focused: true }] } }
      else if (request === 'Workspaces') reply = { Ok: { Workspaces: [{ id: 10, idx: 1, output: 'fixture' }, { id: 20, idx: 2, output: 'fixture' }, { id: 30, idx: 2, output: 'other-monitor' }] } }
      else {
        if (request.Action.MoveWindowToWorkspace) workspace = request.Action.MoveWindowToWorkspace.reference.Id
        reply = { Ok: 'Handled' }
      }
      const output = JSON.stringify(alter ? alter(request, reply) : reply) + '\n'
      // Real private Unix transport and deliberately fragmented framing.
      socket.write(output.slice(0, 2)); socket.end(output.slice(2))
    })
  })
  await new Promise<void>(resolve => server.listen(endpoint, resolve))
  cleanup.push(() => { server.close(); fs.rmSync(root, { recursive: true, force: true }) })
  return { broker: new MissionCompositor({ XDG_RUNTIME_DIR: root, NIRI_SOCKET: endpoint }), requests, root, endpoint }
}

describe('mission-only niri IPC', () => {
  it('verifies PID/title, targets exact window/workspace IDs and checks the moved result', async () => {
    const { broker, requests } = await fixture()
    expect(await broker.locate(title)).toEqual({ focused: false, workspace: 1, width: 800, height: 600 })
    await broker.center(title)
    await broker.move(title, 2)
    expect(await broker.locate(title)).toEqual({ focused: false, workspace: 2, width: 800, height: 600 })
    expect(requests.filter(r => typeof r === 'object')).toEqual([
      { Action: { CenterWindow: { id: 12 } } },
      { Action: { MoveWindowToWorkspace: { window_id: 12, reference: { Id: 20 }, focus: false } } }
    ])
  })
  it.each(['wrong-pid', 'wrong-title', 'duplicate', 'invalid-id', 'missing-geometry'])('denies %s before compositor side effects', async problem => {
    const { broker, requests } = await fixture((request, reply) => {
      if (request !== 'Windows') return reply
      const value = reply as { Ok: { Windows: Record<string, unknown>[] } }, win = value.Ok.Windows[0]
      if (problem === 'wrong-pid') win.pid = process.pid + 1
      if (problem === 'wrong-title') win.title = 'Owner window'
      if (problem === 'duplicate') value.Ok.Windows.push({ ...win })
      if (problem === 'invalid-id') win.id = null
      if (problem === 'missing-geometry') delete win.layout
      return value
    })
    await expect(broker.center(title)).rejects.toThrow()
    expect(requests).toEqual(['Windows'])
  })
  it('denies absent/unsupported workspace and does not invent a successful move', async () => {
    const { broker, requests } = await fixture()
    await expect(broker.move(title, 9)).rejects.toThrow()
    await expect(broker.move(title, 3)).rejects.toThrow()
    expect(requests.every(r => typeof r === 'string')).toBe(true)
  })
  it('denies redirected or public runtime sockets', async () => {
    const { broker, root, endpoint } = await fixture()
    fs.chmodSync(root, 0o755)
    await expect(broker.locate(title)).rejects.toThrow('Untrusted')
    fs.chmodSync(root, 0o700)
    const link = path.join(root, 'redirect.sock'); fs.symlinkSync(endpoint, link)
    await expect(new MissionCompositor({ XDG_RUNTIME_DIR: root, NIRI_SOCKET: link }).locate(title)).rejects.toThrow('Untrusted')
  })
  it('does not leak compositor errors or accept unverified action results', async () => {
    const { broker } = await fixture((request, reply) => typeof request === 'object' ? { Err: 'private compositor content' } : reply)
    await expect(broker.center(title)).rejects.toThrow('Invalid mission compositor reply')
  })
})
