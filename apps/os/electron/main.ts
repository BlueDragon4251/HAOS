import { app, BrowserWindow, globalShortcut, ipcMain, Notification, shell } from 'electron'
import os from 'node:os'
import path from 'node:path'
import { type EnvInfo, type HermesOSPrefs, IPC, type RestRequest, type ShellCommand, type WindowState } from '../shared/ipc.ts'
import { BackendManager } from './backend/manager.ts'
import { registerAppsIpc } from './ipc/apps.ts'
import { registerBridgeIpc } from './ipc/bridge.ts'
import { registerFsIpc } from './ipc/fs.ts'
import { registerSystemIpc } from './ipc/system.ts'
import { registerTerminalIpc } from './ipc/terminal.ts'
import { applyVoiceHotkey, registerVoiceIpc } from './ipc/voice.ts'
import { registerEditIpc } from './ipc/edit.ts'
import { registerWebIpc } from './ipc/web.ts'
import { log, logTail } from './log.ts'
import { hermesHome, hermesOsDataDir, isDev } from './paths.ts'
import { readPrefs, writePrefs } from './prefs.ts'
import { ControlSocket } from './shell/control-socket.ts'
import { shellMode } from './shell/mode.ts'
import { NotificationDaemon } from './shell/notification-daemon.ts'
import { handleUiRequest, OsCommandBridge, OsControlServer, osControlToken } from './shell/os-control.ts'
import { PanelShell } from './shell/panels.ts'
import { registerServiceIpc } from './shell/services.ts'
import { WallpaperService } from './shell/wallpaper.ts'
import { createMainWindow } from './window.ts'

const backend = new BackendManager()
let mainWindow: BrowserWindow | null = null
const mode = shellMode()
// Panels mode (niri): several surface windows, compositor state mirror, control socket for hotkeys.
const panels = mode === 'panels' ? new PanelShell(win => attachMainWindow(win)) : null
const wallpaper = panels ? new WallpaperService(panels) : null
// The agent's `os_ui` tool and the CLI run registry commands in the Hermes window through this bridge.
const osBridge = new OsCommandBridge(() => (panels ? panels.mainWindow() : mainWindow))
const control = panels
  ? new ControlSocket(
      panels,
      next => {
        wallpaper?.apply(next.wallpaper)

        for (const win of BrowserWindow.getAllWindows()) {
          win.webContents.send(IPC.prefsChanged, next)
        }
      },
      osBridge
    )
  : null
// Desktop mode has no compositor CLI socket; the OS control server gives it the same `ui*` surface.
const osControlPath = panels ? path.join(process.env.XDG_RUNTIME_DIR || `/run/user/${process.getuid?.() ?? 1000}`, 'hermes-os', 'control.sock') : path.join(hermesOsDataDir(), 'control.sock')
const osControl = panels
  ? null
  : new OsControlServer(osControlPath, async request => {
      const ui = await handleUiRequest(request as unknown as Parameters<typeof handleUiRequest>[0], osBridge)

      if (ui) {
        return ui
      }

      // A few CLI conveniences the Linux socket also offers, relayed as ShellCommands.
      const cmd = String(request.cmd ?? '')
      const args = Array.isArray(request.args) ? (request.args as string[]) : []
      const relay = (command: ShellCommand) => {
        mainWindow?.webContents.send(IPC.shellCommand, command)
        mainWindow?.show()
      }

      switch (cmd) {
        case 'page':
          relay({ type: 'show-page', args })

          return { ok: true }
        case 'notify':
          relay({ type: 'notify', args })

          return { ok: true }
        case 'voice':
          relay({ type: 'voice', args: [args[0] ?? 'toggle'] })

          return { ok: true }
        case 'os':
          relay({ type: 'os', args: [args[0]], payload: args[1] ? (JSON.parse(args[1]) as Record<string, unknown>) : undefined })

          return { ok: true }
        default:
          return { ok: false, error: `unknown command ${cmd}` }
      }
    })
backend.setControl(osControlPath, osControlToken())
// Serves org.freedesktop.Notifications so other apps' notifications reach the shell.
const notifications = panels ? new NotificationDaemon(panels) : null

if (!app.requestSingleInstanceLock()) {
  app.quit()
}

app.setName('Hermes OS')

function windowState(win: BrowserWindow): WindowState {
  return { fullscreen: win.isFullScreen(), focused: win.isFocused() }
}

function broadcastWindowState(): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(IPC.windowState, windowState(mainWindow))
  }
}

function registerCoreIpc(): void {
  ipcMain.handle(IPC.backendGetState, () => backend.getState())
  ipcMain.handle(IPC.backendRestart, () => backend.restart())
  ipcMain.handle(IPC.backendRest, (_event, request: RestRequest) => backend.rest(request))
  ipcMain.handle(IPC.backendLogTail, (_event, lines: number) => [...logTail(lines), ...backend.getState().logTail])

  ipcMain.handle(IPC.notifyNative, (_event, title: string, body: string) => {
    if (Notification.isSupported()) {
      new Notification({ title: String(title).slice(0, 120), body: String(body).slice(0, 400), silent: true }).show()
    }
  })

  ipcMain.handle(IPC.windowGetState, () => (mainWindow ? windowState(mainWindow) : { fullscreen: false, focused: false }))
  ipcMain.handle(IPC.windowToggleFullscreen, () => {
    if (mainWindow) {
      mainWindow.setFullScreen(!mainWindow.isFullScreen())
    }
  })
  ipcMain.handle(IPC.windowQuit, () => app.quit())

  ipcMain.handle(IPC.shellOpenExternal, (_event, url: string) => {
    if (/^https?:\/\//i.test(url)) {
      return shell.openExternal(url)
    }

    throw new Error('only http(s) URLs may be opened externally')
  })

  ipcMain.handle(IPC.prefsGet, () => readPrefs())
  ipcMain.handle(IPC.prefsSet, (_event, patch: Partial<HermesOSPrefs>) => {
    const next = writePrefs(patch)

    if ('wallpaper' in patch) {
      wallpaper?.apply(next.wallpaper)
    }

    if (patch.voice) {
      applyVoiceHotkey(next.voice.enabled ? next.voice.hotkey : '', () => BrowserWindow.getAllWindows())
    }

    // Every surface window sees the same preferences.
    for (const win of BrowserWindow.getAllWindows()) {
      if (win.webContents !== _event.sender) {
        win.webContents.send(IPC.prefsChanged, next)
      }
    }

    return next
  })

  ipcMain.handle(
    IPC.envInfo,
    (): EnvInfo => ({ platform: process.platform, hermesHome: hermesHome(), homeDir: os.homedir(), version: app.getVersion(), isDev, shellMode: mode })
  )

  registerFsIpc(() => mainWindow)
  registerAppsIpc()
  registerBridgeIpc()
  registerServiceIpc()
  registerSystemIpc(() => BrowserWindow.getAllWindows())
  registerTerminalIpc(() => mainWindow)
  registerVoiceIpc(backend)
  // Desktop mode layers pages over the shell window; panels mode gives them compositor windows.
  const webViews = registerWebIpc(mode === 'desktop')
  registerEditIpc(() => webViews)
}

function attachMainWindow(win: BrowserWindow): void {
  mainWindow = win

  win.on('enter-full-screen', broadcastWindowState)
  win.on('leave-full-screen', broadcastWindowState)
  win.on('focus', broadcastWindowState)
  win.on('blur', broadcastWindowState)

  win.on('closed', () => {
    if (mainWindow === win) {
      mainWindow = null
    }
  })
}

function createWindow(): void {
  if (panels) {
    panels.start()
    void notifications?.start()
    control?.start()
    wallpaper?.start(readPrefs().wallpaper)

    return
  }

  attachMainWindow(createMainWindow(readPrefs()))
  osControl?.start()
}

app.whenReady().then(async () => {
  log('main', `Hermes OS ${app.getVersion()} starting (dev=${isDev}, mode=${mode}, HERMES_HOME=${hermesHome()})`)
  registerCoreIpc()
  backend.onState(state => {
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send(IPC.backendState, state)
    }
  })
  createWindow()
  // Cmd+Ctrl+F is the standard macOS fullscreen toggle; register it as a local shortcut so the
  // user can always leave the environment. Only this shortcut follows focus: the voice hotkey
  // (ipc/voice.ts) must keep working while another app is in front.
  const fullscreenAccelerator = process.platform === 'darwin' ? 'Command+Control+F' : 'F11'
  app.on('browser-window-focus', () => {
    globalShortcut.register(fullscreenAccelerator, () => {
      mainWindow?.setFullScreen(!mainWindow.isFullScreen())
    })
  })
  app.on('browser-window-blur', () => globalShortcut.unregister(fullscreenAccelerator))
  const voicePrefs = readPrefs().voice
  applyVoiceHotkey(voicePrefs.enabled ? voicePrefs.hotkey : '', () => BrowserWindow.getAllWindows())
  void backend.start()
})

app.on('second-instance', () => {
  if (mainWindow) {
    mainWindow.show()
    mainWindow.focus()
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})

app.on('window-all-closed', () => {
  // In panels mode the menu bar and dock keep the session alive; closing the Hermes window is fine.
  if (!panels) {
    app.quit()
  }
})

let quitting = false
app.on('before-quit', event => {
  if (quitting) {
    return
  }

  quitting = true
  event.preventDefault()
  globalShortcut.unregisterAll()
  control?.stop()
  osControl?.stop()
  wallpaper?.stop()
  notifications?.stop()
  panels?.stop()
  void backend.stop().finally(() => app.quit())
})
