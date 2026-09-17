import { contextBridge, ipcRenderer } from 'electron'
import {
  type AuditEntry,
  type BackendState,
  type DirEntry,
  type EnvInfo,
  type FilePreview,
  type HermesOSPrefs,
  type InstalledApp,
  IPC,
  type ProcessInfo,
  type RestRequest,
  type SystemInfo,
  type SystemStats,
  type TerminalCreateOptions,
  type TerminalHandle,
  type WindowState
} from '../shared/ipc.ts'

type Unsubscribe = () => void

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
    openIn: (editor: 'vscode' | 'cursor' | 'finder' | 'terminal', target: string): Promise<void> => ipcRenderer.invoke(IPC.fsOpenIn, editor, target)
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
    openExternal: (url: string): Promise<void> => ipcRenderer.invoke(IPC.shellOpenExternal, url)
  },
  prefs: {
    get: (): Promise<HermesOSPrefs> => ipcRenderer.invoke(IPC.prefsGet),
    set: (patch: Partial<HermesOSPrefs>): Promise<HermesOSPrefs> => ipcRenderer.invoke(IPC.prefsSet, patch)
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
