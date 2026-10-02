import { BrowserWindow, globalShortcut, ipcMain, session, systemPreferences } from 'electron'
import { type AudioWsKind, IPC, type MicPermission } from '../../shared/ipc.ts'
import type { BackendManager } from '../backend/manager.ts'
import { log } from '../log.ts'

/** Chromium permission names the shell grants for its own origin; everything else stays denied. */
const MEDIA_PERMISSIONS = new Set(['media', 'audioCapture', 'speaker-selection'])

/**
 * Voice plumbing owned by main: the microphone permission gate, tokenized audio WebSocket URLs
 * (so the renderer can dial `/api/audio/speak-stream` the same way it dials the gateway), and the
 * global hotkey that toggles a conversation from any app.
 */
export function registerVoiceIpc(backend: BackendManager): void {
  installMediaPermissions()

  ipcMain.handle(IPC.voiceMicrophoneStatus, (): MicPermission => microphoneStatus())
  ipcMain.handle(IPC.voiceRequestMicrophone, async (): Promise<MicPermission> => {
    if (process.platform !== 'darwin') {
      return 'granted'
    }

    const granted = await systemPreferences.askForMediaAccess('microphone')

    return granted ? 'granted' : microphoneStatus()
  })
  ipcMain.handle(IPC.voiceAudioWsUrl, (_event, kind: AudioWsKind) => backend.audioWsUrl(kind))
}

function microphoneStatus(): MicPermission {
  if (process.platform !== 'darwin') {
    return 'granted'
  }

  const status = systemPreferences.getMediaAccessStatus('microphone')

  return status === 'granted' || status === 'denied' || status === 'restricted' || status === 'not-determined' ? status : 'unknown'
}

function installMediaPermissions(): void {
  const allowed = (permission: string, requestingUrl: string, mediaTypes?: readonly string[]): boolean => {
    if (!MEDIA_PERMISSIONS.has(permission)) {
      return false
    }

    // The shell is the only page these windows load (dev server or file://); never a remote origin.
    if (!/^(file:|http:\/\/127\.0\.0\.1|http:\/\/localhost)/.test(requestingUrl)) {
      return false
    }

    // `media` with a video request is not something the shell asks for.
    return !mediaTypes || mediaTypes.every(type => type === 'audio')
  }

  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const url = webContents?.getURL() ?? details.requestingUrl ?? ''
    const mediaTypes = 'mediaTypes' in details ? details.mediaTypes : undefined
    callback(allowed(permission, url, mediaTypes))
  })
  session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
    const url = webContents?.getURL() ?? requestingOrigin ?? ''
    const mediaType = 'mediaType' in details ? details.mediaType : undefined

    return allowed(permission, url, mediaType ? [mediaType] : undefined)
  })
}

let registeredHotkey: string | null = null

/**
 * Register (or re-register) the voice hotkey. Unlike the fullscreen shortcut this one stays active
 * while the window is blurred: the whole point is reaching Hermes from inside another app.
 */
export function applyVoiceHotkey(accelerator: string, getWindows: () => BrowserWindow[]): void {
  if (registeredHotkey) {
    globalShortcut.unregister(registeredHotkey)
    registeredHotkey = null
  }

  const next = accelerator.trim()

  if (!next) {
    return
  }

  try {
    const ok = globalShortcut.register(next, () => {
      for (const win of getWindows()) {
        if (!win.isDestroyed()) {
          win.webContents.send(IPC.voiceHotkey)
        }
      }
    })

    if (ok) {
      registeredHotkey = next
    } else {
      log('voice', `hotkey ${next} could not be registered (taken by another app?)`)
    }
  } catch (error) {
    log('voice', `hotkey ${next} rejected: ${error instanceof Error ? error.message : String(error)}`)
  }
}

export function currentVoiceHotkey(): string | null {
  return registeredHotkey
}
