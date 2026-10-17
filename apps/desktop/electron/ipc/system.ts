import fs from 'node:fs'

const HAOS_UPDATE_STATUS = '/run/haos-update/status.json'

/** Return only a whitelisted non-secret update receipt; no arbitrary file reads. */
export function readHaosUpdateStatus() {
  if (process.platform !== 'linux' || !fs.existsSync('/etc/haos/enabled')) {
    return null
  }
  const empty = { version: 1, channel: 'unconfigured', auto_stage: false,
    state: 'not-checked', reboot_required: false, checked_at: null, message: null } as const
  try {
    const stat = fs.lstatSync(HAOS_UPDATE_STATUS)
    if (!stat.isFile() || stat.isSymbolicLink() || stat.uid !== 0 || stat.size > 2048
        || (stat.mode & 0o022) !== 0) {
      return empty
    }
    const data: unknown = JSON.parse(fs.readFileSync(HAOS_UPDATE_STATUS, 'utf8'))
    if (!data || typeof data !== 'object' || Array.isArray(data)) return empty
    const v = data as Record<string, unknown>
    const channels = ['dev', 'stable', 'unconfigured']
    const states = ['unconfigured', 'configured', 'checking', 'checked', 'up-to-date',
      'update-available', 'staged', 'offline-or-error']
    if (v.version !== 1 || !channels.includes(String(v.channel))
        || !states.includes(String(v.state)) || typeof v.auto_stage !== 'boolean'
        || typeof v.reboot_required !== 'boolean'
        || typeof v.checked_at !== 'string'
        || (v.message !== null && !['registry unavailable', 'bootc check failed',
                                    'bootc stage failed'].includes(String(v.message)))) {
      return empty
    }
    return {
      version: 1 as const,
      channel: v.channel as 'dev' | 'stable' | 'unconfigured',
      auto_stage: v.auto_stage,
      state: v.state as typeof states[number],
      reboot_required: v.reboot_required,
      checked_at: v.checked_at,
      message: v.message as string | null
    }
  } catch {
    return empty
  }
}
import { type BrowserWindow, ipcMain } from 'electron'
import { IPC } from '../../shared/ipc.ts'
import { hostPlatform } from '../platform/index.ts'

const STATS_INTERVAL_MS = 2000

/**
 * System facts. Stats stream to the renderer only while at least one window has subscribed, and
 * the sampler stops when nothing is listening.
 */
export function registerSystemIpc(getWindows: () => BrowserWindow[]): void {
  const platform = hostPlatform()
  let subscribers = 0
  let timer: ReturnType<typeof setInterval> | null = null
  let sampling = false

  const tick = async () => {
    if (sampling) {
      return
    }

    sampling = true

    try {
      const stats = await platform.sampleStats()

      for (const win of getWindows()) {
        if (!win.isDestroyed()) {
          win.webContents.send(IPC.systemStatsPush, stats)
        }
      }
    } catch {
      // A failed sample is skipped; the next tick tries again.
    } finally {
      sampling = false
    }
  }

  ipcMain.handle(IPC.systemInfo, () => platform.systemInfo())
  ipcMain.handle(IPC.systemHaosUpdate, () => readHaosUpdateStatus())
  ipcMain.handle(IPC.systemNetwork, () => platform.networkStatus())
  ipcMain.handle(IPC.calendarToday, () => platform.calendarToday())
  ipcMain.handle(IPC.systemStats, () => platform.sampleStats())
  ipcMain.handle(IPC.systemProcesses, (_event, sort: 'cpu' | 'memory', limit: number) =>
    platform.listProcesses(sort === 'memory' ? 'memory' : 'cpu', Math.max(1, Math.min(200, Number(limit) || 25)))
  )
  ipcMain.handle(IPC.systemStatsSubscribe, (_event, on: boolean) => {
    subscribers = Math.max(0, subscribers + (on ? 1 : -1))

    if (subscribers > 0 && !timer) {
      void tick()
      timer = setInterval(() => void tick(), STATS_INTERVAL_MS)
    } else if (subscribers === 0 && timer) {
      clearInterval(timer)
      timer = null
    }
  })
}
