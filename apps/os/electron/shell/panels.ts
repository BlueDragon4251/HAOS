import { BrowserWindow, ipcMain, screen } from 'electron'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { IPC, type ShellCommand, type ShellSurface, type WmAction } from '../../shared/ipc.ts'
import { log } from '../log.ts'
import { devServerUrl } from '../paths.ts'
import { NiriClient } from '../wm/niri.ts'
import { FLOATING_APPS, shellMode, surfaceTitle } from './mode.ts'

const here = path.dirname(fileURLToPath(import.meta.url))

const MENUBAR_HEIGHT = 30
const DOCK_SIZE = { width: 720, height: 84 }
const COMMAND_SIZE = { width: 680, height: 560 }
const MAIN_SIZE = { width: 1280, height: 800 }

interface SurfaceWindowOptions {
  width: number
  height: number
  transparent?: boolean
  resizable?: boolean
  focusable?: boolean
  show?: boolean
  offscreen?: boolean
}

/**
 * Panels mode: the shell is a set of windows the compositor places (niri window rules match their
 * titles). This class owns those windows, relays commands between them, and mirrors compositor
 * state to every renderer.
 */
export class PanelShell {
  readonly niri = new NiriClient()
  private readonly windows = new Map<ShellSurface, BrowserWindow>()
  private readonly pending = new Map<ShellSurface, ShellCommand[]>()
  private readonly loaded = new Set<ShellSurface>()

  constructor(private readonly onMainCreated: (win: BrowserWindow) => void) {}

  start(): void {
    this.niri.start()
    this.niri.onState(state => {
      for (const win of BrowserWindow.getAllWindows()) {
        if (!win.isDestroyed()) {
          win.webContents.send(IPC.wmState, state)
        }
      }
    })

    ipcMain.handle(IPC.wmGetState, () => this.niri.state())
    ipcMain.handle(IPC.wmAction, (_event, action: WmAction) => this.niri.action(action))
    ipcMain.handle(IPC.shellOpen, (_event, surface: ShellSurface, command?: ShellCommand) => this.open(surface, command))
    ipcMain.handle(IPC.shellClose, (event, surface?: ShellSurface) => {
      const target = surface ?? this.surfaceOf(event.sender.id)

      if (target) {
        this.close(target)
      }
    })
    ipcMain.handle(IPC.shellRelay, (_event, target: ShellSurface, command: ShellCommand) => this.relay(target, command))
    ipcMain.handle(IPC.shellResize, (event, width: number, height: number) => {
      const surface = this.surfaceOf(event.sender.id)
      const win = surface ? this.windows.get(surface) : undefined

      if (win && !win.isDestroyed()) {
        win.setSize(Math.round(width), Math.round(height))
      }
    })

    this.open('main')
    this.open('menubar')
    this.open('dock')
  }

  stop(): void {
    this.niri.stop()
  }

  mainWindow(): BrowserWindow | null {
    const win = this.windows.get('main')

    return win && !win.isDestroyed() ? win : null
  }

  surfaceOf(webContentsId: number): ShellSurface | null {
    for (const [surface, win] of this.windows) {
      if (!win.isDestroyed() && win.webContents.id === webContentsId) {
        return surface
      }
    }

    return null
  }

  /** Create (or raise) a surface window; optionally deliver a command once it is loaded. */
  open(surface: ShellSurface, command?: ShellCommand): void {
    let win = this.windows.get(surface)

    if (!win || win.isDestroyed()) {
      win = this.create(surface)
    } else if (surface === 'command' || surface.startsWith('window:')) {
      win.show()
      win.focus()
    }

    if (command) {
      this.relay(surface, command)
    }

    if (surface !== 'menubar' && surface !== 'dock' && surface !== 'wallpaper') {
      void this.focusInCompositor(surface)
    }
  }

  close(surface: ShellSurface): void {
    const win = this.windows.get(surface)

    if (win && !win.isDestroyed()) {
      win.close()
    }
  }

  /** Deliver a command to a surface, opening it first when needed. */
  relay(target: ShellSurface, command: ShellCommand): void {
    let win = this.windows.get(target)

    if (!win || win.isDestroyed()) {
      win = this.create(target)
    }

    if (this.loaded.has(target)) {
      win.webContents.send(IPC.shellCommand, command)
    } else {
      const queue = this.pending.get(target) ?? []
      queue.push(command)
      this.pending.set(target, queue)
    }
  }

  /** Ask the compositor to focus one of our windows (it knows them by title and pid). */
  async focusInCompositor(surface: ShellSurface): Promise<void> {
    if (!this.niri.available) {
      return
    }

    const title = surfaceTitle(surface)
    // The compositor learns about a new window a moment after Electron creates it.
    for (let attempt = 0; attempt < 10; attempt++) {
      const target = this.niri.ourWindow(title)

      if (target) {
        await this.niri.action({ type: 'focus-window', id: target.id }).catch(() => undefined)

        return
      }

      await new Promise(resolve => setTimeout(resolve, 100))
    }
  }

  private create(surface: ShellSurface): BrowserWindow {
    const display = screen.getPrimaryDisplay()
    const options = this.optionsFor(surface, display.workAreaSize.width, display.size)
    const win = new BrowserWindow({
      width: options.width,
      height: options.height,
      show: options.show ?? true,
      frame: false,
      transparent: options.transparent ?? false,
      resizable: options.resizable ?? true,
      focusable: options.focusable ?? true,
      skipTaskbar: true,
      title: surfaceTitle(surface),
      backgroundColor: options.transparent ? '#00000000' : '#07080a',
      webPreferences: {
        preload: path.join(here, '..', 'preload.cjs'),
        contextIsolation: true,
        sandbox: true,
        nodeIntegration: false,
        webSecurity: true,
        spellcheck: false,
        offscreen: options.offscreen ?? false,
        additionalArguments: [`--hermes-surface=${surface}`, `--hermes-shell-mode=${shellMode()}`]
      }
    })

    // The renderer must not rename the window: niri rules key on the title.
    win.on('page-title-updated', event => event.preventDefault())
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))

    const dev = devServerUrl()

    if (dev) {
      const url = new URL(dev)
      url.searchParams.set('surface', surface)
      void win.loadURL(url.toString())
    } else {
      void win.loadFile(path.join(here, '..', 'renderer', 'index.html'), { query: { surface } })
    }

    win.webContents.on('did-finish-load', () => {
      this.loaded.add(surface)

      for (const command of this.pending.get(surface) ?? []) {
        win.webContents.send(IPC.shellCommand, command)
      }

      this.pending.delete(surface)
      win.webContents.send(IPC.wmState, this.niri.state())
    })

    if (surface === 'command') {
      // Overlays dismiss when focus leaves them (the renderer also closes on Escape).
      win.on('blur', () => setTimeout(() => !win.isDestroyed() && !win.isFocused() && win.close(), 150))
    }

    win.on('closed', () => {
      this.windows.delete(surface)
      this.loaded.delete(surface)
      this.pending.delete(surface)
    })

    this.windows.set(surface, win)

    if (surface === 'main') {
      this.onMainCreated(win)
    }

    log('shell', `opened surface ${surface} (${options.width}x${options.height})`)

    return win
  }

  private optionsFor(surface: ShellSurface, screenWidth: number, size: Electron.Size): SurfaceWindowOptions {
    switch (surface) {
      case 'menubar':
        return { width: screenWidth, height: MENUBAR_HEIGHT, transparent: true, resizable: false }
      case 'dock':
        return { ...DOCK_SIZE, transparent: true, resizable: false }
      case 'command':
        return { ...COMMAND_SIZE, transparent: true, resizable: false }
      case 'wallpaper':
        return { width: size.width, height: size.height, show: false, offscreen: true, focusable: false }
      case 'main':
      case 'desktop':
        return { ...MAIN_SIZE }
      default: {
        const app = FLOATING_APPS[surface.slice('window:'.length)]

        return app ? { width: app.width, height: app.height } : { ...MAIN_SIZE }
      }
    }
  }
}
