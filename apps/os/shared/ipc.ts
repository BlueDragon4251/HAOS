// Typed contract between Electron main, the preload bridge and the renderer.
// Everything the renderer can ask the machine to do is declared here; nothing else is exposed.

export type BackendPhase = 'idle' | 'resolving' | 'starting' | 'ready' | 'restarting' | 'failed' | 'stopped'

export interface BackendRuntime {
  /** How the runtime was found: env override, managed install, or PATH shim. */
  kind: 'env' | 'managed' | 'path'
  label: string
  /** Source checkout root when known (managed install / env override). */
  root?: string
  command: string[]
}

export interface BackendState {
  phase: BackendPhase
  attempt: number
  runtime?: BackendRuntime
  wsUrl?: string
  baseUrl?: string
  port?: number
  error?: string
  logTail: string[]
}

export interface RestRequest {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  body?: unknown
  query?: Record<string, string | number | boolean | undefined>
}

export interface SystemInfo {
  hostname: string
  platform: NodeJS.Platform
  arch: string
  osVersion: string
  osName: string
  cpuModel: string
  cpuCount: number
  totalMemory: number
  userName: string
  /** Account display name when the platform exposes one. */
  fullName?: string
  homeDir: string
}

export interface DiskUsage {
  mount: string
  total: number
  free: number
  used: number
}

export interface BatteryStatus {
  present: boolean
  percent?: number
  charging?: boolean
}

export interface SystemStats {
  sampledAt: number
  cpuPercent: number
  loadAverage: [number, number, number]
  memoryTotal: number
  memoryUsed: number
  memoryFree: number
  uptimeSeconds: number
  disks: DiskUsage[]
  battery: BatteryStatus
}

export interface ProcessInfo {
  pid: number
  ppid: number
  user: string
  cpuPercent: number
  memPercent: number
  rssBytes: number
  command: string
  name: string
}

export interface InstalledApp {
  name: string
  path: string
  bundleId?: string
  /** LSApplicationCategoryType, e.g. public.app-category.developer-tools. */
  category?: string
}

export interface NetworkStatus {
  online: boolean
  defaultInterface?: string
  ipv4?: string
  wifi?: { connected: boolean; ssid?: string; interface?: string }
}

export interface CalendarEvent {
  id: string
  title: string
  start: number
  end: number
  allDay: boolean
  location?: string
  notes?: string
  calendar?: string
  url?: string
}

export interface CalendarResult {
  status: 'authorized' | 'denied' | 'not-determined' | 'restricted' | 'unavailable'
  events: CalendarEvent[]
  error?: string
}

export interface RecentFile {
  path: string
  name: string
  extension: string
  size: number
  modifiedAt: number
  lastUsedAt: number
  kind: 'file' | 'directory'
}

export interface ImageInfo {
  width: number
  height: number
}

export interface DirEntry {
  name: string
  path: string
  kind: 'file' | 'directory' | 'symlink' | 'other'
  size: number
  modifiedAt: number
  hidden: boolean
  extension: string
}

export interface FilePreview {
  path: string
  kind: 'text' | 'image' | 'binary' | 'too-large' | 'directory'
  size: number
  /** Text content (utf-8) or a data URL for images. */
  content?: string
  truncated?: boolean
  mime?: string
}

export interface TerminalCreateOptions {
  cwd?: string
  cols: number
  rows: number
}

export interface TerminalHandle {
  id: string
  pid: number
  shell: string
}

export interface SpaceDef {
  id: string
  name: string
  color: string
  cwd?: string
}

export interface HermesOSPrefs {
  fullscreenOnLaunch: boolean
  reduceMotion: boolean
  accent: 'blue' | 'ice' | 'violet'
  theme: 'ocean' | 'graphite'
  /** Absolute path or file:// URL of a custom wallpaper image. */
  wallpaper?: string
  defaultCwd?: string
  spaces: SpaceDef[]
  activeSpace: string
  favorites: string[]
  /** Persisted window bounds per app id. */
  windowBounds?: Record<string, { x: number; y: number; width: number; height: number }>
  /** Main-window sidebar: expanded width in px and whether it is collapsed to icons. */
  sidebar?: { width: number; collapsed: boolean }
}

export interface AuditEntry {
  ts: string
  tool: string
  tier: string
  action?: string
  decision: string
  ok: boolean
  error?: string
  summary?: string
  args?: Record<string, unknown>
}

export interface WindowState {
  fullscreen: boolean
  focused: boolean
}

export interface EnvInfo {
  platform: NodeJS.Platform
  hermesHome: string
  homeDir: string
  version: string
  isDev: boolean
}

/** Channel names, table-driven so preload and main cannot drift. */
export const IPC = {
  backendGetState: 'hermes-os:backend:get-state',
  backendState: 'hermes-os:backend:state',
  backendRestart: 'hermes-os:backend:restart',
  backendRest: 'hermes-os:backend:rest',
  backendLogTail: 'hermes-os:backend:log-tail',

  systemInfo: 'hermes-os:system:info',
  systemStats: 'hermes-os:system:stats',
  systemStatsPush: 'hermes-os:system:stats-push',
  systemStatsSubscribe: 'hermes-os:system:stats-subscribe',
  systemProcesses: 'hermes-os:system:processes',

  appsList: 'hermes-os:apps:list',
  appsLaunch: 'hermes-os:apps:launch',
  appsIcon: 'hermes-os:apps:icon',

  fsHome: 'hermes-os:fs:home',
  fsReadDir: 'hermes-os:fs:read-dir',
  fsReadFile: 'hermes-os:fs:read-file',
  fsReveal: 'hermes-os:fs:reveal',
  fsOpenPath: 'hermes-os:fs:open-path',
  fsOpenIn: 'hermes-os:fs:open-in',
  fsRecent: 'hermes-os:fs:recent',
  fsThumbnail: 'hermes-os:fs:thumbnail',
  fsImageInfo: 'hermes-os:fs:image-info',
  fsWriteText: 'hermes-os:fs:write-text',
  fsMkdir: 'hermes-os:fs:mkdir',
  fsRename: 'hermes-os:fs:rename',
  fsTrash: 'hermes-os:fs:trash',
  fsExportPdf: 'hermes-os:fs:export-pdf',
  fsPickFiles: 'hermes-os:fs:pick-files',
  fsDirSize: 'hermes-os:fs:dir-size',

  systemNetwork: 'hermes-os:system:network',
  calendarToday: 'hermes-os:calendar:today',

  terminalCreate: 'hermes-os:terminal:create',
  terminalWrite: 'hermes-os:terminal:write',
  terminalResize: 'hermes-os:terminal:resize',
  terminalDispose: 'hermes-os:terminal:dispose',
  terminalData: 'hermes-os:terminal:data',
  terminalExit: 'hermes-os:terminal:exit',

  notifyNative: 'hermes-os:notify:native',

  windowState: 'hermes-os:window:state',
  windowGetState: 'hermes-os:window:get-state',
  windowToggleFullscreen: 'hermes-os:window:toggle-fullscreen',
  windowQuit: 'hermes-os:window:quit',

  shellOpenExternal: 'hermes-os:shell:open-external',

  prefsGet: 'hermes-os:prefs:get',
  prefsSet: 'hermes-os:prefs:set',

  bridgePolicyRead: 'hermes-os:bridge:policy-read',
  bridgePolicyWrite: 'hermes-os:bridge:policy-write',
  bridgeAuditRead: 'hermes-os:bridge:audit-read',

  envInfo: 'hermes-os:env:info'
} as const
