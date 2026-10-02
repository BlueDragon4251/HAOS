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

/** Which pipeline turns speech into a Hermes turn and back. See docs/VOICE.md. */
export type VoiceEngine = 'chained' | 'live'

export interface VoicePrefs {
  /** Master switch: when off, no microphone is ever opened and the orb stays hidden. */
  enabled: boolean
  engine: VoiceEngine
  /** Arm the backend "hey hermes" detector with client-captured audio while the shell runs. */
  wakeWord: boolean
  /** Electron accelerator toggling a conversation from anywhere (empty disables the hotkey). */
  hotkey: string
  /** Seconds the mic keeps listening for a follow-up after Hermes finishes speaking. */
  followUpSeconds: number
  /** Speak `notification.show` bodies (missions, reminders) aloud while voice is enabled. */
  announceNotifications: boolean
  /** Show Hermes's own tool results on screen (memory, automations, files) even outside a voice conversation. */
  followHermes: boolean
  /** Set once Herald OS has tuned local speech recognition (model + vocabulary), so a later user choice is never overwritten. */
  sttTuned: boolean
  /** Live engine: close the paid session after this many idle seconds. */
  liveIdleSeconds: number
  /** Live engine: refuse to open new sessions once today's minutes reach this cap (0 = no cap). */
  liveDailyCapMinutes: number
  /** Live engine: seconds of session time used on `day` (YYYY-MM-DD, local). */
  liveUsage: { day: string; seconds: number }
}

export type MicPermission = 'granted' | 'denied' | 'not-determined' | 'restricted' | 'unknown'

/** Keyboard modifiers for `EditAction` key presses (Electron accelerator names). */
export type KeyModifier = 'shift' | 'control' | 'alt' | 'meta'

/** Text and editing actions performed on whatever is focused in a Herald OS window. */
export type EditAction =
  | { kind: 'insert'; text: string }
  | { kind: 'key'; key: string; modifiers?: KeyModifier[] }
  | { kind: 'copy' | 'cut' | 'paste' | 'selectAll' | 'undo' | 'redo' | 'delete' | 'unselect' }

/** Main -> renderer: run a registry command, list the catalogue, or describe the shell state. */
export type OsControlRequest =
  | { requestId: string; kind: 'run'; command: string; args: Record<string, unknown>; source: 'agent' | 'cli' }
  | { requestId: string; kind: 'list' }
  | { requestId: string; kind: 'state' }

export interface OsControlReply {
  requestId: string
  /** A `CommandResult`, a command list, or a state snapshot; `error` when the renderer failed outright. */
  result?: unknown
  error?: string
}

/** Authenticated WebSocket endpoints the renderer may dial besides the gateway. */
export type AudioWsKind = 'speak-stream'

export interface HeraldOSPrefs {
  fullscreenOnLaunch: boolean
  reduceMotion: boolean
  accent: 'blue' | 'ice' | 'violet'
  theme: 'ocean' | 'graphite'
  /** Absolute path or file:// URL of a custom wallpaper image. */
  wallpaper?: string
  defaultCwd?: string
  /** Where "build …" creates project folders (default ~/Projects). */
  projectsRoot?: string
  spaces: SpaceDef[]
  activeSpace: string
  favorites: string[]
  /** Files the user removed from Recents (the system's own recent list is left alone). */
  hiddenRecents?: string[]
  /** Persisted window bounds per app id. */
  windowBounds?: Record<string, { x: number; y: number; width: number; height: number }>
  /** Main-window sidebar: expanded width in px and whether it is collapsed to icons. */
  sidebar?: { width: number; collapsed: boolean }
  /** Slide the Dock off-screen until the cursor reaches the bottom edge (default on). */
  dockAutoHide?: boolean
  voice: VoicePrefs
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

/**
 * How the shell is composed on screen.
 * - `desktop`: one fullscreen window draws wallpaper, menu bar, dock and windows (macOS, cage).
 * - `panels`: a real compositor (niri) manages every window; the shell is several windows, one per surface.
 */
export type ShellMode = 'desktop' | 'panels'

/** Which part of the shell a renderer window is. `window:<appId>` hosts one floating Hermes app. */
export type ShellSurface = 'desktop' | 'menubar' | 'dock' | 'main' | 'command' | 'wallpaper' | `window:${string}`

/** A window the compositor manages (any client, including the shell's own windows). */
export interface WmWindow {
  id: number
  title: string
  appId: string
  pid: number | null
  workspaceId: number | null
  focused: boolean
  floating: boolean
  urgent: boolean
  /** True for the shell's own windows (menu bar, dock, Hermes window, floating apps). */
  ours: boolean
}

export interface WmWorkspace {
  id: number
  idx: number
  name: string | null
  output: string | null
  active: boolean
  focused: boolean
  activeWindowId: number | null
}

export interface WmState {
  /** False when no compositor IPC is available (desktop mode). */
  available: boolean
  windows: WmWindow[]
  workspaces: WmWorkspace[]
  focusedWindowId: number | null
}

/** Compositor actions the renderer may request. Arguments mirror `niri msg action`. */
export type WmAction =
  | { type: 'focus-window'; id: number }
  | { type: 'close-window'; id: number }
  | { type: 'focus-workspace'; ref: string | number }
  | { type: 'move-window-to-workspace'; id: number; ref: string | number }
  | { type: 'toggle-floating'; id: number }
  | { type: 'fullscreen'; id: number }
  | { type: 'maximize-column' }
  | { type: 'toggle-overview' }
  | { type: 'screenshot'; what: 'screen' | 'window' | 'select' }
  | { type: 'raw'; args: string[] }

/** A command delivered to a surface: from the `herald-os` CLI (hotkeys), or relayed between surfaces. */
export interface ShellCommand {
  type: string
  args?: string[]
  text?: string
  attachments?: string[]
  /** The compositor's focused window when the command was issued (context for "ask"). */
  context?: WmWindow | null
  payload?: Record<string, unknown>
}

/** A rectangle in the renderer's CSS pixels; main converts to device-independent pixels. */
export interface WebViewBounds {
  x: number
  y: number
  width: number
  height: number
  /** Corner radius matching the frame around the view (CSS px). */
  radius?: number
}

export interface WebOpenOptions {
  /** Fixed window title; when omitted the page title is reported through `title` events. */
  title?: string
  /** Previews only: the project folder whose local files the preview may show. */
  root?: string
}

/** Main -> renderer: lifecycle of one embedded web view (`window.heraldOS.web`). */
export type WebViewEvent =
  | { id: string; type: 'title'; title: string }
  | { id: string; type: 'url'; url: string }
  | { id: string; type: 'loading'; loading: boolean }
  | { id: string; type: 'error'; error: string }
  | { id: string; type: 'closed' }

/** One entry of a project listing (`fs.listTree`), for the Studio's file tree. */
export interface TreeEntry {
  path: string
  kind: 'file' | 'directory'
}

/** Main -> renderer: files changed under a watched project folder (`fs.watchTree`). */
export interface TreeChangedEvent {
  watchId: string
  paths: string[]
}

export interface EnvInfo {
  platform: NodeJS.Platform
  hermesHome: string
  homeDir: string
  version: string
  isDev: boolean
  shellMode: ShellMode
}

/** Channel names, table-driven so preload and main cannot drift. */
export const IPC = {
  backendGetState: 'herald-os:backend:get-state',
  backendState: 'herald-os:backend:state',
  backendRestart: 'herald-os:backend:restart',
  backendRest: 'herald-os:backend:rest',
  backendLogTail: 'herald-os:backend:log-tail',

  systemInfo: 'herald-os:system:info',
  systemStats: 'herald-os:system:stats',
  systemStatsPush: 'herald-os:system:stats-push',
  systemStatsSubscribe: 'herald-os:system:stats-subscribe',
  systemProcesses: 'herald-os:system:processes',

  appsList: 'herald-os:apps:list',
  appsLaunch: 'herald-os:apps:launch',
  appsIcon: 'herald-os:apps:icon',

  fsHome: 'herald-os:fs:home',
  fsReadDir: 'herald-os:fs:read-dir',
  fsReadFile: 'herald-os:fs:read-file',
  fsReveal: 'herald-os:fs:reveal',
  fsOpenPath: 'herald-os:fs:open-path',
  fsOpenIn: 'herald-os:fs:open-in',
  fsRecent: 'herald-os:fs:recent',
  /** Find files by name under the home folder (Spotlight on macOS). */
  fsFind: 'herald-os:fs:find',
  fsThumbnail: 'herald-os:fs:thumbnail',
  fsImageInfo: 'herald-os:fs:image-info',
  fsWriteText: 'herald-os:fs:write-text',
  fsMkdir: 'herald-os:fs:mkdir',
  fsRename: 'herald-os:fs:rename',
  fsTrash: 'herald-os:fs:trash',
  fsExportPdf: 'herald-os:fs:export-pdf',
  fsPickFiles: 'herald-os:fs:pick-files',
  fsDirSize: 'herald-os:fs:dir-size',
  /** A bounded recursive listing of a project folder (build output and dependencies skipped). */
  fsListTree: 'herald-os:fs:list-tree',
  fsWatchTree: 'herald-os:fs:watch-tree',
  fsUnwatchTree: 'herald-os:fs:unwatch-tree',
  /** Main -> renderer: `TreeChangedEvent`. */
  fsTreeChanged: 'herald-os:fs:tree-changed',

  systemNetwork: 'herald-os:system:network',
  calendarToday: 'herald-os:calendar:today',

  terminalCreate: 'herald-os:terminal:create',
  terminalWrite: 'herald-os:terminal:write',
  terminalResize: 'herald-os:terminal:resize',
  terminalDispose: 'herald-os:terminal:dispose',
  terminalData: 'herald-os:terminal:data',
  terminalExit: 'herald-os:terminal:exit',

  notifyNative: 'herald-os:notify:native',

  windowState: 'herald-os:window:state',
  windowGetState: 'herald-os:window:get-state',
  windowToggleFullscreen: 'herald-os:window:toggle-fullscreen',
  windowQuit: 'herald-os:window:quit',

  shellOpenExternal: 'herald-os:shell:open-external',

  // Embedded web views: http(s) pages rendered inside a Herald OS window, never the system browser.
  /** Perform an `EditAction` in this window (or in one of its web views). */
  editAction: 'herald-os:edit:action',
  webOpen: 'herald-os:web:open',
  /** Show a local file (PDF, image, text, media) in a locked-down viewer view. */
  webOpenFile: 'herald-os:web:open-file',
  webSetBounds: 'herald-os:web:set-bounds',
  webClose: 'herald-os:web:close',
  /** Studio preview: a web page or a file inside the project folder. */
  webOpenPreview: 'herald-os:web:open-preview',
  webNavigate: 'herald-os:web:navigate',
  webReload: 'herald-os:web:reload',
  /** Main -> renderer: title/url/loading changes and `closed`. */
  webEvent: 'herald-os:web:event',

  prefsGet: 'herald-os:prefs:get',
  prefsSet: 'herald-os:prefs:set',
  prefsChanged: 'herald-os:prefs:changed',

  bridgePolicyRead: 'herald-os:bridge:policy-read',
  bridgePolicyWrite: 'herald-os:bridge:policy-write',
  bridgeAuditRead: 'herald-os:bridge:audit-read',

  envInfo: 'herald-os:env:info',

  // OS control: main asks the Hermes window to run a registry command (from the control socket /
  // the agent's os_ui tool) and the window replies.
  osControlRequest: 'herald-os:os-control:request',
  osControlReply: 'herald-os:os-control:reply',

  // Voice: microphone permission, tokenized audio WebSocket URLs, the global hotkey.
  voiceRequestMicrophone: 'herald-os:voice:request-microphone',
  voiceMicrophoneStatus: 'herald-os:voice:microphone-status',
  voiceAudioWsUrl: 'herald-os:voice:audio-ws-url',
  /** Main -> renderer: the global voice hotkey was pressed. */
  voiceHotkey: 'herald-os:voice:hotkey',

  // Panels mode: surfaces, cross-window relay, compositor state.
  shellOpen: 'herald-os:shell:open',
  shellClose: 'herald-os:shell:close',
  shellRelay: 'herald-os:shell:relay',
  shellCommand: 'herald-os:shell:command',
  shellResize: 'herald-os:shell:resize',
  shellWallpaperFrame: 'herald-os:shell:wallpaper-frame',
  wmGetState: 'herald-os:wm:get-state',
  wmState: 'herald-os:wm:state',
  wmAction: 'herald-os:wm:action',

  // Phase 2: system services reachable from any surface.
  /** Run a `herald-os` CLI command (install, reminder, notice, ocr, …); resolves with its output. */
  shellHeraldOs: 'herald-os:shell:herald-os',
  /** Power actions: suspend | reboot | poweroff | logout | lock. */
  shellPower: 'herald-os:shell:power',
  /** Clipboard history (cliphist): list entries / paste one back to the clipboard. */
  clipboardHistory: 'herald-os:clipboard:history',
  clipboardPaste: 'herald-os:clipboard:paste',
  /** Desktop notifications from other apps (org.freedesktop.Notifications), pushed to the Hermes window. */
  notificationsIncoming: 'herald-os:notifications:incoming',
  notificationsAction: 'herald-os:notifications:action'
} as const

export type PowerAction = 'suspend' | 'reboot' | 'poweroff' | 'logout' | 'lock'

export interface ClipboardEntry {
  id: string
  /** Text preview (binary entries show a type label such as "[[ binary data 12 KiB png ]]"). */
  preview: string
}

/** A notification received from another application through the freedesktop D-Bus service. */
export interface IncomingNotification {
  id: number
  appName: string
  summary: string
  body: string
  /** Icon name or path as sent by the app, if any. */
  icon?: string
  /** Pairs of [actionKey, label]; the renderer reports a chosen key through `notificationsAction`. */
  actions: Array<[string, string]>
  urgency: 'low' | 'normal' | 'critical'
  /** Milliseconds; -1 lets the shell decide. */
  expireTimeout: number
}

export interface HeraldOsResult {
  code: number
  stdout: string
  stderr: string
}
