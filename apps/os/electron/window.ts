import { BrowserWindow, screen, shell } from 'electron'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import type { HermesOSPrefs } from '../shared/ipc.ts'
import { devServerUrl } from './paths.ts'

const here = path.dirname(fileURLToPath(import.meta.url))

export function createMainWindow(prefs: HermesOSPrefs): BrowserWindow {
  const { workAreaSize } = screen.getPrimaryDisplay()
  const win = new BrowserWindow({
    width: workAreaSize.width,
    height: workAreaSize.height,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    frame: false,
    titleBarStyle: 'hidden',
    // Hermes OS is its own environment: launch fullscreen on its own Space. `simpleFullscreen`
    // keeps the menu bar hidden without the macOS fullscreen animation on every toggle.
    // HERMES_OS_WINDOWED=1 is a developer escape hatch for automated runs and screenshots.
    fullscreen: prefs.fullscreenOnLaunch && !process.env.HERMES_OS_WINDOWED,
    simpleFullscreen: false,
    fullscreenable: true,
    backgroundColor: '#07080a',
    vibrancy: 'under-window',
    visualEffectState: 'active',
    webPreferences: {
      preload: path.join(here, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false
    }
  })

  // Links stay outside: the renderer must never navigate away from the shell.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) {
      void shell.openExternal(url)
    }

    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (event, url) => {
    const allowed = devServerUrl()

    if (!(allowed && url.startsWith(allowed)) && !url.startsWith('file:')) {
      event.preventDefault()
    }
  })

  const dev = devServerUrl()

  if (dev) {
    void win.loadURL(dev)
  } else {
    void win.loadFile(path.join(here, '..', 'renderer', 'index.html'))
  }

  win.once('ready-to-show', () => win.show())

  return win
}
