/** Narrow compositor control for windows already owned by MissionBrowser.
 * No spawn, global input, clipboard, screenshot, arbitrary IPC action or window ID API.
 */
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'

type Window = { id: number; pid: number; title: string; workspace_id: number | null; is_focused: boolean; layout: { window_size: [number, number] } }
type Workspace = { id: number; idx: number; output: string | null }

export class MissionCompositor {
  constructor(private env: NodeJS.ProcessEnv = process.env, private pid = process.pid) {}

  private socket(): string {
    const runtime = this.env.XDG_RUNTIME_DIR, endpoint = this.env.NIRI_SOCKET
    if (!runtime || !endpoint || !path.isAbsolute(runtime) || path.dirname(endpoint) !== runtime || Buffer.byteLength(endpoint) > 107) throw new Error('Mission compositor unavailable')
    const dir = fs.lstatSync(runtime), file = fs.lstatSync(endpoint)
    if (!dir.isDirectory() || dir.isSymbolicLink() || fs.realpathSync(runtime) !== runtime || dir.uid !== process.getuid?.() || dir.mode & 0o077 || !file.isSocket() || file.uid !== dir.uid || file.isSymbolicLink()) throw new Error('Untrusted mission compositor')
    return endpoint
  }

  private request(request: unknown): Promise<unknown> {
    const endpoint = this.socket()
    return new Promise((resolve, reject) => {
      const socket = net.createConnection(endpoint)
      let data = Buffer.alloc(0), settled = false
      // Absolute deadline: a trickling peer must not renew the request lease.
      const timer = setTimeout(() => finish(new Error('Mission compositor deadline exceeded')), 1000)
      const finish = (error?: Error, result?: unknown) => {
        if (settled) return
        settled = true; clearTimeout(timer); socket.destroy()
        if (error) reject(error); else resolve(result)
      }
      socket.once('error', () => finish(new Error('Mission compositor unavailable')))
      socket.once('end', () => finish(new Error('Incomplete mission compositor reply')))
      socket.once('connect', () => socket.write(JSON.stringify(request) + '\n'))
      socket.on('data', chunk => {
        if (data.length + chunk.length > 1024 * 1024) return finish(new Error('Mission compositor response budget exceeded'))
        data = Buffer.concat([data, chunk])
        const end = data.indexOf(10)
        if (end < 0) return
        try {
          const value = JSON.parse(data.subarray(0, end).toString('utf8'))
          if (!value || Object.keys(value).length !== 1 || !Object.hasOwn(value, 'Ok')) throw new Error()
          finish(undefined, value.Ok)
        } catch { finish(new Error('Invalid mission compositor reply')) }
      })
    })
  }

  private async owned(title: string): Promise<Window> {
    const reply = await this.request('Windows') as { Windows?: Window[] }
    if (!Array.isArray(reply?.Windows) || reply.Windows.length > 256) throw new Error('Invalid compositor inventory')
    const matches = reply.Windows.filter(win => win.pid === this.pid && win.title === title)
    if (matches.length !== 1) throw new Error('Mission window identity is ambiguous')
    const win = matches[0]
    if (!Number.isSafeInteger(win.id) || win.id < 1 || typeof win.is_focused !== 'boolean' || (win.workspace_id !== null && (!Number.isSafeInteger(win.workspace_id) || win.workspace_id < 1)) || !Array.isArray(win.layout?.window_size) || win.layout.window_size.length !== 2 || win.layout.window_size.some(x => !Number.isInteger(x) || x < 1 || x > 16384)) throw new Error('Invalid mission window metadata')
    return win
  }

  private async workspaces(): Promise<Workspace[]> {
    const reply = await this.request('Workspaces') as { Workspaces?: Workspace[] }
    if (!Array.isArray(reply?.Workspaces) || reply.Workspaces.length > 256 || reply.Workspaces.some(w => !Number.isSafeInteger(w.id) || w.id < 1 || !Number.isInteger(w.idx) || w.idx < 1 || w.idx > 255 || (w.output !== null && typeof w.output !== 'string'))) throw new Error('Invalid compositor workspaces')
    return reply.Workspaces
  }

  async locate(title: string): Promise<{ focused: boolean; workspace: number | null; width: number; height: number }> {
    const win = await this.owned(title)
    const spaces = await this.workspaces()
    const matches = spaces.filter(w => w.id === win.workspace_id)
    if (matches.length > 1 || (win.workspace_id !== null && matches.length !== 1)) throw new Error('Ambiguous mission workspace')
    return { focused: win.is_focused, workspace: matches[0]?.idx ?? null, width: win.layout.window_size[0], height: win.layout.window_size[1] }
  }

  async move(title: string, index: number): Promise<void> {
    if (!Number.isInteger(index) || index < 1 || index > 8) throw new Error('Mission workspace denied')
    const win = await this.owned(title), spaces = await this.workspaces()
    const current = spaces.filter(w => w.id === win.workspace_id)
    if (current.length !== 1 || current[0].output === null) throw new Error('Mission output unavailable')
    const targets = spaces.filter(w => w.output === current[0].output && w.idx === index)
    if (targets.length !== 1) throw new Error('Mission workspace unavailable')
    // Explicit ID only; never act on the focused window or move an entire workspace.
    if (await this.request({ Action: { MoveWindowToWorkspace: { window_id: win.id, reference: { Id: targets[0].id }, focus: false } } }) !== 'Handled') throw new Error('Mission workspace move failed')
    const after = await this.owned(title)
    if (after.id !== win.id || after.workspace_id !== targets[0].id) throw new Error('Mission workspace move was not verified')
  }

  async center(title: string): Promise<void> {
    const win = await this.owned(title)
    if (await this.request({ Action: { CenterWindow: { id: win.id } } }) !== 'Handled') throw new Error('Mission centering failed')
    if ((await this.owned(title)).id !== win.id) throw new Error('Mission window disappeared')
  }
}
