import { type BrowserWindow, ipcMain } from 'electron'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'
import { IPC, type TerminalCreateOptions, type TerminalHandle } from '../../shared/ipc.ts'
import { log } from '../log.ts'
import { normalizeUserPath } from './fs.ts'

interface PtyLike {
  pid: number
  write(data: string): void
  resize(cols: number, rows: number): void
  kill(signal?: string): void
  onData(listener: (data: string) => void): { dispose(): void }
  onExit(listener: (event: { exitCode: number; signal?: number }) => void): { dispose(): void }
}

interface PtyModule {
  spawn(file: string, args: string[], options: Record<string, unknown>): PtyLike
}

let ptyModule: PtyModule | null | undefined

/**
 * npm strips the executable bit from node-pty's prebuilt `spawn-helper` (the tarball ships it
 * 0644), and pty.spawn then fails with `posix_spawnp failed`. Restore it before the first load.
 */
export function ensureSpawnHelperExecutable(ptyEntry: string): void {
  if (process.platform === 'win32') {
    return
  }

  const helper = path.join(path.dirname(path.dirname(ptyEntry)), 'prebuilds', `${process.platform}-${process.arch}`, 'spawn-helper')

  try {
    const mode = fs.statSync(helper).mode

    if ((mode & 0o111) === 0) {
      fs.chmodSync(helper, mode | 0o755)
      log('terminal', `restored executable bit on ${helper}`)
    }
  } catch {
    // No prebuilt helper (compiled from source); nothing to fix.
  }
}

function loadPty(): PtyModule | null {
  if (ptyModule !== undefined) {
    return ptyModule
  }

  try {
    const require = createRequire(import.meta.url)
    ensureSpawnHelperExecutable(require.resolve('node-pty'))
    ptyModule = require('node-pty') as PtyModule
  } catch (error) {
    log('terminal', `node-pty unavailable: ${error instanceof Error ? error.message : String(error)}`)
    ptyModule = null
  }

  return ptyModule
}

/** Real PTYs for the Terminal surface. One id per tab; output is pushed to the owning window. */
export function registerTerminalIpc(getWindow: () => BrowserWindow | null): void {
  const sessions = new Map<string, PtyLike>()
  let nextId = 1

  ipcMain.handle(IPC.terminalCreate, (_event, options: TerminalCreateOptions): TerminalHandle => {
    const pty = loadPty()

    if (!pty) {
      throw new Error('Terminal is unavailable: node-pty failed to load for this Electron build.')
    }

    const shell = process.env.SHELL || (process.platform === 'win32' ? 'powershell.exe' : '/bin/zsh')
    const cwd = options.cwd ? normalizeUserPath(options.cwd) : os.homedir()
    const id = `t${nextId++}`
    const child = pty.spawn(shell, process.platform === 'win32' ? [] : ['-l'], {
      name: 'xterm-256color',
      cols: Math.max(2, options.cols),
      rows: Math.max(1, options.rows),
      cwd,
      env: { ...process.env, TERM: 'xterm-256color', COLORTERM: 'truecolor', TERM_PROGRAM: 'HermesOS', LANG: process.env.LANG || 'en_US.UTF-8' }
    })
    sessions.set(id, child)

    child.onData(data => {
      getWindow()?.webContents.send(IPC.terminalData, id, data)
    })
    child.onExit(({ exitCode }) => {
      sessions.delete(id)
      getWindow()?.webContents.send(IPC.terminalExit, id, exitCode)
    })

    return { id, pid: child.pid, shell }
  })

  ipcMain.on(IPC.terminalWrite, (_event, id: string, data: string) => {
    sessions.get(id)?.write(data)
  })
  ipcMain.on(IPC.terminalResize, (_event, id: string, cols: number, rows: number) => {
    try {
      sessions.get(id)?.resize(Math.max(2, cols), Math.max(1, rows))
    } catch {
      // Resizing a dying pty throws; ignore.
    }
  })
  ipcMain.handle(IPC.terminalDispose, (_event, id: string) => {
    const child = sessions.get(id)
    sessions.delete(id)

    try {
      child?.kill()
    } catch {
      // Already exited.
    }
  })
}
