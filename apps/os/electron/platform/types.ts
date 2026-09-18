import type { CalendarResult, InstalledApp, NetworkStatus, ProcessInfo, RecentFile, SystemInfo, SystemStats } from '../../shared/ipc.ts'

export type EditorTarget = 'vscode' | 'cursor' | 'finder' | 'terminal'

/**
 * Machine facts and actions the SHELL needs (not the agent; that is the plugin's HostAdapter).
 * One implementation per platform; the rest of main never branches on process.platform.
 */
export interface HostPlatform {
  systemInfo(): Promise<SystemInfo>
  sampleStats(): Promise<SystemStats>
  listProcesses(sort: 'cpu' | 'memory', limit: number): Promise<ProcessInfo[]>
  listInstalledApps(): Promise<InstalledApp[]>
  /** PNG bytes for an application's icon, or null when none can be produced. */
  appIcon(appPath: string): Promise<Buffer | null>
  /** Launch an installed application by the `path` reported in `InstalledApp` (bundle, `.desktop` entry, ...). */
  launchApp(appPath: string): Promise<void>
  /** Show a file or folder selected in the platform's file manager. */
  revealPath(targetPath: string): Promise<void>
  openIn(target: EditorTarget, targetPath: string): Promise<void>
  networkStatus(): Promise<NetworkStatus>
  /** Today's calendar events (with the permission state), or `unavailable` on platforms without a bridge. */
  calendarToday(): Promise<CalendarResult>
  /** Recently used documents under the user's folders. */
  recentFiles(limit: number): Promise<RecentFile[]>
  /** PNG thumbnail bytes for any file (QuickLook on macOS), or null. */
  thumbnail(filePath: string, size: number): Promise<Buffer | null>
}

export class HostNotSupported extends Error {
  /**
   * @param feature What was asked for, e.g. `openIn(vscode)`.
   * @param requires When the gap is a missing host package rather than missing code, name it
   *   (e.g. `NetworkManager (nmcli)`) so the UI can tell the user what to install.
   */
  constructor(feature: string, requires?: string) {
    super(requires ? `${feature} requires ${requires}, which is not installed` : `${feature} is not implemented for ${process.platform} yet`)
    this.name = 'HostNotSupported'
  }
}
