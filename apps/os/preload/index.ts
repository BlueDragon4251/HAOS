import { contextBridge, ipcRenderer, webUtils } from 'electron'
import {
  type AuditEntry,
  type BackendState,
  type CalendarResult,
  type DirEntry,
  type EnvInfo,
  type FilePreview,
  type HermesOSPrefs,
  type ImageInfo,
  type InstalledApp,
  IPC,
  type NetworkStatus,
  type ProcessInfo,
  type RecentFile,
  type RestRequest,
  type ShellCommand,
  type ShellMode,
  type ShellSurface,
  type SystemInfo,
  type SystemStats,
  type TerminalCreateOptions,
  type TerminalHandle,
  type WindowState,
  type WmAction,
  type WmState
} from '../shared/ipc.ts'

type Unsubscribe = () => void

// Main passes the surface identity as extra Chromium switches so it is known before any IPC.
const argValue = (name: string): string | undefined => process.argv.find(arg => arg.startsWith(`--${name}=`))?.slice(name.length + 3)
const SURFACE = (argValue('hermes-surface') ?? 'desktop') as ShellSurface
const SHELL_MODE = (argValue('hermes-shell-mode') === 'panels' ? 'panels' : 'desktop') as ShellMode

const subscribe = <T,>(channel: string, listener: (payload: T) => void): Unsubscribe => {
  const wrapped = (_event: unknown, payload: T) => listener(payload)
  ipcRenderer.on(channel, wrapped)

  return () => ipcRenderer.removeListener(channel, wrapped)
}

/** The whole capability surface the renderer gets. Keep it narrow and typed. */
const api = {
  backend: {
    getState: (): Promise<BackendState> => ipcRenderer.invoke(IPC.backendGetState),
    onState: (listener: (state: BackendState) => void): Unsubscribe => subscribe(IPC.backendState, listener),
    restart: (): Promise<void> => ipcRenderer.invoke(IPC.backendRestart),
    rest: <T,>(request: RestRequest): Promise<T> => ipcRenderer.invoke(IPC.backendRest, request),
    logTail: (lines = 200): Promise<string[]> => ipcRenderer.invoke(IPC.backendLogTail, lines)
  },
  system: {
    info: (): Promise<SystemInfo> => ipcRenderer.invoke(IPC.systemInfo),
    stats: (): Promise<SystemStats> => ipcRenderer.invoke(IPC.systemStats),
    processes: (sort: 'cpu' | 'memory', limit: number): Promise<ProcessInfo[]> => ipcRenderer.invoke(IPC.systemProcesses, sort, limit),
    network: (): Promise<NetworkStatus> => ipcRenderer.invoke(IPC.systemNetwork),
    subscribeStats: (listener: (stats: SystemStats) => void): Unsubscribe => {
      const off = subscribe(IPC.systemStatsPush, listener)
      void ipcRenderer.invoke(IPC.systemStatsSubscribe, true)

      return () => {
        off()
        void ipcRenderer.invoke(IPC.systemStatsSubscribe, false)
      }
    }
  },
  apps: {
    list: (): Promise<InstalledApp[]> => ipcRenderer.invoke(IPC.appsList),
    launch: (appPath: string): Promise<void> => ipcRenderer.invoke(IPC.appsLaunch, appPath),
    icon: (appPath: string): Promise<string> => ipcRenderer.invoke(IPC.appsIcon, appPath)
  },
  fs: {
    home: (): Promise<string> => ipcRenderer.invoke(IPC.fsHome),
    readDir: (target: string): Promise<DirEntry[]> => ipcRenderer.invoke(IPC.fsReadDir, target),
    readFile: (target: string): Promise<FilePreview> => ipcRenderer.invoke(IPC.fsReadFile, target),
    reveal: (target: string): Promise<void> => ipcRenderer.invoke(IPC.fsReveal, target),
    openPath: (target: string): Promise<void> => ipcRenderer.invoke(IPC.fsOpenPath, target),
    openIn: (editor: 'vscode' | 'cursor' | 'finder' | 'terminal', target: string): Promise<void> => ipcRenderer.invoke(IPC.fsOpenIn, editor, target),
    recent: (limit = 30): Promise<RecentFile[]> => ipcRenderer.invoke(IPC.fsRecent, limit),
    thumbnail: (target: string, size = 512): Promise<string | null> => ipcRenderer.invoke(IPC.fsThumbnail, target, size),
    imageInfo: (target: string): Promise<ImageInfo | null> => ipcRenderer.invoke(IPC.fsImageInfo, target),
    writeText: (target: string, content: string): Promise<void> => ipcRenderer.invoke(IPC.fsWriteText, target, content),
    mkdir: (target: string): Promise<void> => ipcRenderer.invoke(IPC.fsMkdir, target),
    rename: (from: string, to: string): Promise<void> => ipcRenderer.invoke(IPC.fsRename, from, to),
    trash: (targets: string[]): Promise<void> => ipcRenderer.invoke(IPC.fsTrash, targets),
    exportPdf: (html: string, suggestedName: string): Promise<string | null> => ipcRenderer.invoke(IPC.fsExportPdf, html, suggestedName),
    pickFiles: (options?: { directory?: boolean; multiple?: boolean }): Promise<string[]> => ipcRenderer.invoke(IPC.fsPickFiles, options ?? {}),
    dirSize: (target: string): Promise<{ bytes: number; files: number; complete: boolean }> => ipcRenderer.invoke(IPC.fsDirSize, target),
    /** Absolute path of a File dropped from Finder (Electron removed File.path). */
    pathForFile: (file: File): string => {
      try {
        return webUtils.getPathForFile(file)
      } catch {
        return ''
      }
    }
  },
  calendar: {
    today: (): Promise<CalendarResult> => ipcRenderer.invoke(IPC.calendarToday)
  },
  terminal: {
    create: (options: TerminalCreateOptions): Promise<TerminalHandle> => ipcRenderer.invoke(IPC.terminalCreate, options),
    write: (id: string, data: string): void => ipcRenderer.send(IPC.terminalWrite, id, data),
    resize: (id: string, cols: number, rows: number): void => ipcRenderer.send(IPC.terminalResize, id, cols, rows),
    dispose: (id: string): Promise<void> => ipcRenderer.invoke(IPC.terminalDispose, id),
    onData: (listener: (id: string, data: string) => void): Unsubscribe => {
      const wrapped = (_event: unknown, id: string, data: string) => listener(id, data)
      ipcRenderer.on(IPC.terminalData, wrapped)

      return () => ipcRenderer.removeListener(IPC.terminalData, wrapped)
    },
    onExit: (listener: (id: string, code: number) => void): Unsubscribe => {
      const wrapped = (_event: unknown, id: string, code: number) => listener(id, code)
      ipcRenderer.on(IPC.terminalExit, wrapped)

      return () => ipcRenderer.removeListener(IPC.terminalExit, wrapped)
    }
  },
  notifications: {
    native: (title: string, body: string): Promise<void> => ipcRenderer.invoke(IPC.notifyNative, title, body)
  },
  window: {
    getState: (): Promise<WindowState> => ipcRenderer.invoke(IPC.windowGetState),
    onState: (listener: (state: WindowState) => void): Unsubscribe => subscribe(IPC.windowState, listener),
    toggleFullscreen: (): Promise<void> => ipcRenderer.invoke(IPC.windowToggleFullscreen),
    quit: (): Promise<void> => ipcRenderer.invoke(IPC.windowQuit)
  },
  shell: {
    openExternal: (url: string): Promise<void> => ipcRenderer.invoke(IPC.shellOpenExternal, url),
    /** Which surface this window is, and how the shell is composed. Known synchronously at load. */
    surface: SURFACE,
    mode: SHELL_MODE,
    /** Panels mode: open a surface window (optionally delivering a command to it). */
    open: (surface: ShellSurface, command?: ShellCommand): Promise<void> => ipcRenderer.invoke(IPC.shellOpen, surface, command),
    /** Close a surface window (this one when omitted). */
    close: (surface?: ShellSurface): Promise<void> => ipcRenderer.invoke(IPC.shellClose, surface),
    /** Deliver a command to another surface (e.g. the command overlay asking main to send a prompt). */
    relay: (target: ShellSurface, command: ShellCommand): Promise<void> => ipcRenderer.invoke(IPC.shellRelay, target, command),
    /** Commands arriving for this surface: from the `hermes-os` CLI (hotkeys) or another surface. */
    onCommand: (listener: (command: ShellCommand) => void): Unsubscribe => subscribe(IPC.shellCommand, listener),
    /** Ask main to resize this surface window (overlays size to their content). */
    resize: (width: number, height: number): Promise<void> => ipcRenderer.invoke(IPC.shellResize, width, height),
    /** Wallpaper surface only: hand a rendered PNG frame to main for swaybg. */
    wallpaperFrame: (dataUrl: string): Promise<void> => ipcRenderer.invoke(IPC.shellWallpaperFrame, dataUrl)
  },
  wm: {
    getState: (): Promise<WmState> => ipcRenderer.invoke(IPC.wmGetState),
    onState: (listener: (state: WmState) => void): Unsubscribe => subscribe(IPC.wmState, listener),
    action: (action: WmAction): Promise<void> => ipcRenderer.invoke(IPC.wmAction, action)
  },
  prefs: {
    get: (): Promise<HermesOSPrefs> => ipcRenderer.invoke(IPC.prefsGet),
    set: (patch: Partial<HermesOSPrefs>): Promise<HermesOSPrefs> => ipcRenderer.invoke(IPC.prefsSet, patch),
    /** Preferences changed from another surface window. */
    onChanged: (listener: (prefs: HermesOSPrefs) => void): Unsubscribe => subscribe(IPC.prefsChanged, listener)
  },
  bridge: {
    readPolicy: (): Promise<string> => ipcRenderer.invoke(IPC.bridgePolicyRead),
    writePolicy: (text: string): Promise<void> => ipcRenderer.invoke(IPC.bridgePolicyWrite, text),
    readAudit: (limit = 200): Promise<AuditEntry[]> => ipcRenderer.invoke(IPC.bridgeAuditRead, limit)
  },
  env: (): Promise<EnvInfo> => ipcRenderer.invoke(IPC.envInfo)
}

export type HermesOSApi = typeof api

contextBridge.exposeInMainWorld('hermesOS', api)
