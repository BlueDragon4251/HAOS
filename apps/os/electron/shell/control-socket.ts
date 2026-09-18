import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import type { ShellCommand } from '../../shared/ipc.ts'
import { hostPlatform } from '../platform/index.ts'
import { log } from '../log.ts'
import type { PanelShell } from './panels.ts'

interface ControlRequest {
  cmd: string
  args?: string[]
  attachments?: string[]
}

/** Commands that open the command overlay in a given mode, with the focused window as context. */
const OVERLAY_MODES = new Set(['ask', 'command', 'applications', 'menu', 'power', 'clipboard'])

/**
 * Unix socket the `hermes-os` CLI (and therefore every compositor hotkey) talks to:
 * one JSON object per line in, one JSON object per line out.
 */
export class ControlSocket {
  private server: net.Server | null = null

  constructor(private readonly shell: PanelShell) {}

  get socketPath(): string {
    const runtime = process.env.XDG_RUNTIME_DIR || `/run/user/${process.getuid?.() ?? 1000}`

    return path.join(runtime, 'hermes-os', 'control.sock')
  }

  start(): void {
    const socketPath = this.socketPath
    fs.mkdirSync(path.dirname(socketPath), { recursive: true, mode: 0o700 })

    try {
      fs.unlinkSync(socketPath)
    } catch {
      // Not there.
    }

    this.server = net.createServer(connection => {
      let buffer = ''
      connection.setEncoding('utf8')
      connection.on('data', chunk => {
        buffer += chunk
        let index = buffer.indexOf('\n')

        while (index >= 0) {
          const line = buffer.slice(0, index).trim()
          buffer = buffer.slice(index + 1)

          if (line) {
            void this.handleLine(line).then(reply => connection.write(`${JSON.stringify(reply)}\n`))
          }

          index = buffer.indexOf('\n')
        }
      })
      connection.on('error', () => undefined)
    })
    this.server.on('error', error => log('control', `socket error: ${error.message}`))
    this.server.listen(socketPath, () => {
      fs.chmodSync(socketPath, 0o600)
      log('control', `listening on ${socketPath}`)
    })
  }

  stop(): void {
    this.server?.close()
    this.server = null

    try {
      fs.unlinkSync(this.socketPath)
    } catch {
      // Already gone.
    }
  }

  private async handleLine(line: string): Promise<Record<string, unknown>> {
    let request: ControlRequest

    try {
      request = JSON.parse(line) as ControlRequest
    } catch {
      return { ok: false, error: 'invalid JSON' }
    }

    try {
      return await this.handle(request)
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) }
    }
  }

  private async handle(request: ControlRequest): Promise<Record<string, unknown>> {
    const args = request.args ?? []
    const { cmd } = request

    if (OVERLAY_MODES.has(cmd)) {
      const focused = this.shell.niri.focusedWindow()
      const command: ShellCommand = {
        type: cmd,
        args,
        text: args.join(' ') || undefined,
        attachments: request.attachments,
        // Our own windows are not interesting context ("ask about this window" over the Hermes window).
        context: focused && !focused.ours ? focused : null
      }
      this.shell.open('command', command)

      return { ok: true }
    }

    switch (cmd) {
      case 'page': {
        const id = args[0]

        if (!id) {
          return { ok: false, error: 'page needs an id' }
        }

        this.shell.relay('main', { type: 'show-page', args: [id] })
        void this.shell.focusInCompositor('main')

        return { ok: true }
      }
      case 'open': {
        const appId = args[0]

        if (!appId) {
          return { ok: false, error: 'open needs an app id (terminal, system, chat-popout)' }
        }

        this.shell.open(`window:${appId}`)

        return { ok: true }
      }
      case 'launch': {
        const query = args.join(' ').trim().toLowerCase()

        if (!query) {
          return { ok: false, error: 'launch needs an application name' }
        }

        const apps = await hostPlatform().listInstalledApps()
        const match =
          apps.find(a => a.name.toLowerCase() === query) ??
          apps.find(a => (a.bundleId ?? '').toLowerCase() === query) ??
          apps.find(a => a.name.toLowerCase().includes(query)) ??
          apps.find(a => (a.bundleId ?? '').toLowerCase().includes(query))

        if (!match) {
          return { ok: false, error: `no application matches ${query}` }
        }

        await hostPlatform().launchApp(match.path)

        return { ok: true, launched: match.name }
      }
      case 'notify': {
        this.shell.relay('main', { type: 'notify', args })

        return { ok: true }
      }
      case 'state':
        return { ok: true, ...this.shell.niri.state() }
      default:
        return { ok: false, error: `unknown command ${cmd}` }
    }
  }
}
