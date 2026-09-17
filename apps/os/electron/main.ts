import { app, BrowserWindow, globalShortcut, ipcMain, Notification, shell } from 'electron'
import os from 'node:os'
import { type EnvInfo, type HermesOSPrefs, IPC, type RestRequest, type WindowState } from '../shared/ipc.ts'
import { BackendManager } from './backend/manager.ts'
import { registerAppsIpc } from './ipc/apps.ts'
import { registerBridgeIpc } from './ipc/bridge.ts'
import { registerFsIpc } from './ipc/fs.ts'
import { registerSystemIpc } from './ipc/system.ts'
import { registerTerminalIpc } from './ipc/terminal.ts'
import { log, logTail } from './log.ts'
import { hermesHome, isDev } from './paths.ts'
import { readPrefs, writePrefs } from './prefs.ts'
import { createMainWindow } from './window.ts'

const backend = new BackendManager()
let mainWindow: BrowserWindow | null = null

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
  ipcMain.handle(IPC.prefsSet, (_event, patch: Partial<HermesOSPrefs>) => writePrefs(patch))

  ipcMain.handle(
    IPC.envInfo,
    (): EnvInfo => ({ platform: process.platform, hermesHome: hermesHome(), homeDir: os.homedir(), version: app.getVersion(), isDev })
  )

  registerFsIpc(() => mainWindow)
  registerAppsIpc()
  registerBridgeIpc()
  registerSystemIpc(() => BrowserWindow.getAllWindows())
  registerTerminalIpc(() => mainWindow)
}

function createWindow(): void {
  const win = createMainWindow(readPrefs())
  mainWindow = win

  win.on('enter-full-screen', broadcastWindowState)
  win.on('leave-full-screen', broadcastWindowState)
  win.on('focus', broadcastWindowState)
  win.on('blur', broadcastWindowState)

  win.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(async () => {
  log('main', `Hermes OS ${app.getVersion()} starting (dev=${isDev}, HERMES_HOME=${hermesHome()})`)
  registerCoreIpc()
  backend.onState(state => {
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send(IPC.backendState, state)
    }
  })
  createWindow()
  // Cmd+Ctrl+F is the standard macOS fullscreen toggle; register it as a local shortcut so the
  // user can always leave the environment.
  app.on('browser-window-focus', () => {
    globalShortcut.register(process.platform === 'darwin' ? 'Command+Control+F' : 'F11', () => {
      mainWindow?.setFullScreen(!mainWindow.isFullScreen())
    })
  })
  app.on('browser-window-blur', () => globalShortcut.unregisterAll())
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
  app.quit()
})

let quitting = false
app.on('before-quit', event => {
  if (quitting) {
    return
  }

  quitting = true
  event.preventDefault()
  globalShortcut.unregisterAll()
  void backend.stop().finally(() => app.quit())
})
