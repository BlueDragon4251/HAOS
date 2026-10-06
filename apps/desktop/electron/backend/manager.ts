import { type ChildProcess, spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { AudioWsKind, BackendRuntime, BackendState, RestRequest } from '../../shared/ipc.ts'
import { osEnv } from '../env.ts'
import { log } from '../log.ts'
import { hermesHome, heraldOsDataDir } from '../paths.ts'
import { waitForStatus } from './probe.ts'
import { LineBuffer, parseReadyLine, readyFileName, staleReadyFiles } from './ready.ts'
import { resolveBackendRuntime } from './resolve.ts'
import { loginShellPath } from './shell-env.ts'

const READY_TIMEOUT_MS = 90_000
const STATUS_TIMEOUT_MS = 60_000
const MAX_RESTARTS = 4
const BACKOFF_MS = [1_000, 3_000, 7_000, 15_000]
const LOG_TAIL_LINES = 200

export type BackendListener = (state: BackendState) => void

/**
 * Owns the `hermes serve` child: resolve -> spawn -> ready -> probe -> ready state, restart with
 * bounded backoff on unexpected exit, and REST forwarding that adds the token in main (ADR-007).
 */
export class BackendManager {
  private state: BackendState = { phase: 'idle', attempt: 0, logTail: [] }
  private child: ChildProcess | null = null
  private token = ''
  /** Control socket the bridge plugin's `os_ui` tool dials, and the token it must present. */
  private control: { socketPath: string; token: string } | null = null
  private listeners = new Set<BackendListener>()

  setControl(socketPath: string, token: string): void {
    this.control = { socketPath, token }
  }
  private stopping = false
  private startGeneration = 0
  private restartTimer: ReturnType<typeof setTimeout> | null = null
  private readonly tail: string[] = []

  getState(): BackendState {
    return { ...this.state, logTail: this.tail.slice(-LOG_TAIL_LINES) }
  }

  /** Process id of the running `hermes serve`, if any. */
  childPid(): number | null {
    return this.child?.pid ?? null
  }

  onState(listener: BackendListener): () => void {
    this.listeners.add(listener)
    listener(this.getState())

    return () => this.listeners.delete(listener)
  }

  async start(): Promise<void> {
    this.stopping = false
    await this.launch(0)
  }

  /** User-driven restart: resets the attempt budget. */
  async restart(): Promise<void> {
    log('backend', 'restart requested')
    this.clearRestartTimer()
    await this.killChild()
    this.stopping = false
    await this.launch(0)
  }

  async stop(): Promise<void> {
    this.stopping = true
    this.clearRestartTimer()
    await this.killChild()
    this.update({ phase: 'stopped', wsUrl: undefined, baseUrl: undefined, port: undefined })
  }

  /**
   * Tokenized URL for an authenticated audio WebSocket. The renderer already receives the gateway
   * `wsUrl` with the same loopback token, so this widens nothing (ADR-007 amendment).
   */
  audioWsUrl(kind: AudioWsKind): string {
    const { port, phase } = this.state

    if (!port || phase !== 'ready') {
      throw new Error('Hermes backend is not ready')
    }

    const paths: Record<AudioWsKind, string> = { 'speak-stream': '/api/audio/speak-stream' }

    return `ws://127.0.0.1:${port}${paths[kind]}?token=${encodeURIComponent(this.token)}`
  }

  async rest<T>(request: RestRequest): Promise<T> {
    const { baseUrl } = this.state

    if (!baseUrl || this.state.phase !== 'ready') {
      throw new Error('Hermes backend is not ready')
    }

    if (!request.path.startsWith('/api/')) {
      throw new Error(`refusing REST path outside /api: ${request.path}`)
    }

    const url = new URL(baseUrl + request.path)

    for (const [key, value] of Object.entries(request.query ?? {})) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value))
      }
    }

    const response = await fetch(url, {
      method: request.method,
      headers: {
        'X-Hermes-Session-Token': this.token,
        ...(request.body === undefined ? {} : { 'Content-Type': 'application/json' })
      },
      body: request.body === undefined ? undefined : JSON.stringify(request.body),
      signal: AbortSignal.timeout(60_000)
    })

    const text = await response.text()

    if (!response.ok) {
      let detail = response.statusText

      try {
        const parsed = JSON.parse(text) as { detail?: unknown; error?: unknown }
        detail = String(parsed.detail ?? parsed.error ?? detail)
      } catch {
        detail = text || detail
      }

      throw new Error(`${request.method} ${request.path} -> ${response.status}: ${detail}`)
    }

    return (text ? JSON.parse(text) : null) as T
  }

  private async launch(attempt: number): Promise<void> {
    const generation = ++this.startGeneration
    this.update({ phase: attempt === 0 ? 'resolving' : 'restarting', attempt, error: undefined })

    const runtime = resolveBackendRuntime()

    if (!runtime) {
      this.update({
        phase: 'failed',
        error:
          'No Hermes runtime found. Install Hermes Agent (curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash) or set HERALD_OS_HERMES_ROOT.'
      })

      return
    }

    this.update({ runtime, phase: 'starting' })

    try {
      const port = await this.spawnServe(runtime, generation)

      if (generation !== this.startGeneration) {
        return
      }

      const baseUrl = `http://127.0.0.1:${port}`
      await waitForStatus(baseUrl, this.token, STATUS_TIMEOUT_MS)

      if (generation !== this.startGeneration) {
        return
      }

      const wsUrl = `ws://127.0.0.1:${port}/api/ws?token=${encodeURIComponent(this.token)}`
      this.update({ phase: 'ready', port, baseUrl, wsUrl, error: undefined })
      log('backend', `ready on ${baseUrl} via ${runtime.label}`)
    } catch (error) {
      if (generation !== this.startGeneration) {
        return
      }

      const message = error instanceof Error ? error.message : String(error)
      log('backend', `start failed: ${message}`)
      await this.killChild()
      this.scheduleRestart(attempt, message)
    }
  }

  private async spawnServe(runtime: BackendRuntime, generation: number): Promise<number> {
    this.token = crypto.randomBytes(32).toString('base64url')
    const [command, ...head] = runtime.command
    const args = [...head, 'serve', '--host', '127.0.0.1', '--port', '0']
    const dataDir = heraldOsDataDir()
    const readyFile = path.join(dataDir, readyFileName(process.pid))
    fs.mkdirSync(dataDir, { recursive: true })
    fs.rmSync(readyFile, { force: true })

    for (const name of staleReadyFiles(fs.readdirSync(dataDir), process.pid, isProcessAlive)) {
      fs.rmSync(path.join(dataDir, name), { force: true })
    }

    const env: NodeJS.ProcessEnv = {
      ...process.env,
      PATH: await loginShellPath(),
      HERMES_HOME: hermesHome(),
      // Sessions start in the user's world, not inside the runtime checkout.
      TERMINAL_CWD: osEnv('DEFAULT_CWD') || os.homedir(),
      HERMES_DASHBOARD_SESSION_TOKEN: this.token,
      // The loopback token exemption, in-process cron ticker and orphan reaping upstream key on
      // this flag; Herald OS spawns and owns the backend exactly the way Desktop does.
      HERMES_DESKTOP: '1',
      HERALD_OS: '1',
      HERMES_PARENT_PID: String(process.pid),
      HERMES_DESKTOP_READY_FILE: readyFile,
      PYTHONUNBUFFERED: '1',
      ...(this.control ? { HERALD_OS_CONTROL_SOCKET: this.control.socketPath, HERALD_OS_CONTROL_TOKEN: this.control.token } : {})
    }
    delete env.ELECTRON_RUN_AS_NODE

    log('backend', `spawning ${[command, ...args].join(' ')} (cwd ${runtime.root ?? process.cwd()})`)
    const child = spawn(command, args, {
      cwd: runtime.root ?? undefined,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: false
    })
    this.child = child

    return new Promise<number>((resolve, reject) => {
      let settled = false
      const stdout = new LineBuffer()
      const stderr = new LineBuffer()
      const settle = (fn: () => void) => {
        if (!settled) {
          settled = true
          clearTimeout(timer)
          clearInterval(filePoll)
          fs.rmSync(readyFile, { force: true })
          fn()
        }
      }
      const timer = setTimeout(() => settle(() => reject(new Error('timed out waiting for HERMES_BACKEND_READY'))), READY_TIMEOUT_MS)
      // Fallback for interpreters whose fd 1 is not our pipe: upstream also publishes the port in a ready file.
      const filePoll = setInterval(() => {
        try {
          const parsed = JSON.parse(fs.readFileSync(readyFile, 'utf8')) as { port?: unknown }

          if (typeof parsed.port === 'number') {
            settle(() => resolve(parsed.port as number))
          }
        } catch {
          // Not written yet.
        }
      }, 500)

      child.stdout?.setEncoding('utf8')
      child.stdout?.on('data', (chunk: string) => {
        for (const line of stdout.push(chunk)) {
          this.record(`[out] ${line}`)
          const port = parseReadyLine(line)

          if (port !== null) {
            settle(() => resolve(port))
          }
        }
      })
      child.stderr?.setEncoding('utf8')
      child.stderr?.on('data', (chunk: string) => {
        for (const line of stderr.push(chunk)) {
          this.record(`[err] ${line}`)
        }
      })
      child.on('error', error => settle(() => reject(error)))
      child.on('exit', (code, signal) => {
        for (const line of [...stdout.flush(), ...stderr.flush()]) {
          this.record(line)
        }

        log('backend', `serve exited code=${code} signal=${signal}`)

        if (this.child === child) {
          this.child = null
        }

        settle(() => reject(new Error(`hermes serve exited early (code ${code ?? 'null'}, signal ${signal ?? 'none'})`)))

        if (settled && generation === this.startGeneration && !this.stopping && this.state.phase === 'ready') {
          this.scheduleRestart(this.state.attempt, `backend exited unexpectedly (code ${code ?? 'null'})`)
        }
      })
    })
  }

  private scheduleRestart(previousAttempt: number, reason: string): void {
    if (this.stopping) {
      return
    }

    const next = previousAttempt + 1

    if (next > MAX_RESTARTS) {
      this.update({ phase: 'failed', error: reason, wsUrl: undefined, baseUrl: undefined, port: undefined })

      return
    }

    const delay = BACKOFF_MS[Math.min(next - 1, BACKOFF_MS.length - 1)]
    log('backend', `restart ${next}/${MAX_RESTARTS} in ${delay}ms: ${reason}`)
    this.update({ phase: 'restarting', attempt: next, error: reason, wsUrl: undefined, baseUrl: undefined, port: undefined })
    this.clearRestartTimer()
    this.restartTimer = setTimeout(() => void this.launch(next), delay)
  }

  private clearRestartTimer(): void {
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
  }

  private async killChild(): Promise<void> {
    const child = this.child
    this.child = null
    // Any in-flight launch belongs to a previous generation now.
    this.startGeneration++

    if (!child || child.exitCode !== null) {
      return
    }

    await new Promise<void>(resolve => {
      const force = setTimeout(() => {
        try {
          child.kill('SIGKILL')
        } catch {
          // Already gone.
        }

        resolve()
      }, 4000)
      child.once('exit', () => {
        clearTimeout(force)
        resolve()
      })

      try {
        child.kill('SIGTERM')
      } catch {
        clearTimeout(force)
        resolve()
      }
    })
  }

  private record(line: string): void {
    this.tail.push(line)

    if (this.tail.length > LOG_TAIL_LINES * 2) {
      this.tail.splice(0, this.tail.length - LOG_TAIL_LINES)
    }

    log('serve', line)
  }

  private update(patch: Partial<BackendState>): void {
    this.state = { ...this.state, ...patch }
    const snapshot = this.getState()

    for (const listener of this.listeners) {
      listener(snapshot)
    }
  }
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)

    return true
  } catch (error) {
    // EPERM: alive, owned by someone else.
    return (error as NodeJS.ErrnoException).code === 'EPERM'
  }
}
