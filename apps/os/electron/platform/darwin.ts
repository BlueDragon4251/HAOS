import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import type { BatteryStatus, DiskUsage, InstalledApp, ProcessInfo, SystemInfo, SystemStats } from '../../shared/ipc.ts'
import { hermesOsDataDir } from '../paths.ts'
import { run } from './exec.ts'
import { type EditorTarget, type HostPlatform } from './types.ts'

const APP_DIRS = ['/Applications', '/Applications/Utilities', '/System/Applications', '/System/Applications/Utilities', path.join(os.homedir(), 'Applications')]

interface CpuSample {
  idle: number
  total: number
}

function cpuSample(): CpuSample {
  let idle = 0
  let total = 0

  for (const cpu of os.cpus()) {
    idle += cpu.times.idle
    total += cpu.times.user + cpu.times.nice + cpu.times.sys + cpu.times.irq + cpu.times.idle
  }

  return { idle, total }
}

/** Parse `vm_stat` into used bytes (active + wired + compressor), which is what Activity Monitor reports as "used". */
export function parseVmStat(text: string): { pageSize: number; usedBytes: number } | null {
  const pageMatch = /page size of (\d+) bytes/.exec(text)

  if (!pageMatch) {
    return null
  }

  const pageSize = Number(pageMatch[1])
  const pages = (label: string): number => {
    const match = new RegExp(`${label}:\\s+(\\d+)`).exec(text)

    return match ? Number(match[1]) : 0
  }
  const used = pages('Pages active') + pages('Pages wired down') + pages('Pages occupied by compressor')

  return { pageSize, usedBytes: used * pageSize }
}

/** Parse POSIX `df -kP` output into mounted volumes; hides system-internal APFS volumes. */
export function parseDf(text: string): DiskUsage[] {
  const disks: DiskUsage[] = []

  for (const line of text.split('\n').slice(1)) {
    const parts = line.trim().split(/\s+/)

    if (parts.length < 6) {
      continue
    }

    const mount = parts.slice(5).join(' ')
    const total = Number(parts[1]) * 1024
    const used = Number(parts[2]) * 1024
    const free = Number(parts[3]) * 1024

    if (!Number.isFinite(total) || total <= 0) {
      continue
    }

    if (mount === '/' || (mount.startsWith('/Volumes/') && !mount.startsWith('/Volumes/.'))) {
      disks.push({ mount, total, used, free })
    }
  }

  return disks
}

/** Parse `pmset -g batt`. */
export function parsePmset(text: string): BatteryStatus {
  const match = /(\d+)%;\s*([a-zA-Z ]+?);/.exec(text)

  if (!match) {
    return { present: false }
  }

  const state = match[2].trim().toLowerCase()

  return { present: true, percent: Number(match[1]), charging: state === 'charging' || state === 'charged' }
}

/** Parse `ps -Axo pid=,ppid=,user=,%cpu=,%mem=,rss=,comm=` rows. */
export function parsePs(text: string): ProcessInfo[] {
  const rows: ProcessInfo[] = []

  for (const line of text.split('\n')) {
    const match = /^\s*(\d+)\s+(\d+)\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(.*)$/.exec(line)

    if (!match) {
      continue
    }

    const command = match[7].trim()
    rows.push({
      pid: Number(match[1]),
      ppid: Number(match[2]),
      user: match[3],
      cpuPercent: Number(match[4]),
      memPercent: Number(match[5]),
      rssBytes: Number(match[6]) * 1024,
      command,
      name: path.basename(command)
    })
  }

  return rows
}

export class DarwinPlatform implements HostPlatform {
  private previousCpu = cpuSample()
  private appsCache: { at: number; apps: InstalledApp[] } | null = null

  async systemInfo(): Promise<SystemInfo> {
    const [name, version] = await Promise.all([run('sw_vers', ['-productName']), run('sw_vers', ['-productVersion'])])
    const cpus = os.cpus()

    return {
      hostname: os.hostname(),
      platform: process.platform,
      arch: process.arch,
      osName: name.stdout.trim() || 'macOS',
      osVersion: version.stdout.trim(),
      cpuModel: cpus[0]?.model ?? 'Apple Silicon',
      cpuCount: cpus.length,
      totalMemory: os.totalmem(),
      userName: os.userInfo().username,
      homeDir: os.homedir()
    }
  }

  async sampleStats(): Promise<SystemStats> {
    const current = cpuSample()
    const idleDelta = current.idle - this.previousCpu.idle
    const totalDelta = current.total - this.previousCpu.total
    this.previousCpu = current
    const cpuPercent = totalDelta > 0 ? Math.max(0, Math.min(100, (1 - idleDelta / totalDelta) * 100)) : 0

    const [vm, df, batt] = await Promise.all([run('vm_stat', []), run('df', ['-kP']), run('pmset', ['-g', 'batt'])])
    const memoryTotal = os.totalmem()
    const parsedVm = parseVmStat(vm.stdout)
    const memoryUsed = parsedVm ? Math.min(memoryTotal, parsedVm.usedBytes) : memoryTotal - os.freemem()

    return {
      sampledAt: Date.now(),
      cpuPercent,
      loadAverage: os.loadavg() as [number, number, number],
      memoryTotal,
      memoryUsed,
      memoryFree: memoryTotal - memoryUsed,
      uptimeSeconds: os.uptime(),
      disks: parseDf(df.stdout),
      battery: parsePmset(batt.stdout)
    }
  }

  async listProcesses(sort: 'cpu' | 'memory', limit: number): Promise<ProcessInfo[]> {
    const result = await run('ps', ['-Axo', 'pid=,ppid=,user=,%cpu=,%mem=,rss=,comm='])
    const rows = parsePs(result.stdout)
    rows.sort((a, b) => (sort === 'cpu' ? b.cpuPercent - a.cpuPercent : b.rssBytes - a.rssBytes))

    return rows.slice(0, limit)
  }

  async listInstalledApps(): Promise<InstalledApp[]> {
    if (this.appsCache && Date.now() - this.appsCache.at < 60_000) {
      return this.appsCache.apps
    }

    const found = new Map<string, InstalledApp>()

    for (const dir of APP_DIRS) {
      let entries: string[] = []

      try {
        entries = await fs.readdir(dir)
      } catch {
        continue
      }

      for (const entry of entries) {
        if (!entry.endsWith('.app') || entry.startsWith('.')) {
          continue
        }

        const appPath = path.join(dir, entry)
        const name = entry.slice(0, -4)

        if (!found.has(name)) {
          found.set(name, { name, path: appPath })
        }
      }
    }

    const apps = [...found.values()].sort((a, b) => a.name.localeCompare(b.name))
    this.appsCache = { at: Date.now(), apps }

    return apps
  }

  /**
   * `app.getFileIcon` traps Electron 40 on macOS 26, so icons come from the bundle itself:
   * `CFBundleIconFile` -> `sips` renders the .icns to PNG; bundles that only ship an asset
   * catalog fall back to a QuickLook thumbnail (`qlmanage`).
   */
  async appIcon(appPath: string): Promise<Buffer | null> {
    const cacheDir = path.join(hermesOsDataDir(), 'cache', 'icons')
    const cacheFile = path.join(cacheDir, `${crypto.createHash('sha1').update(appPath).digest('hex')}.png`)

    try {
      return await fs.readFile(cacheFile)
    } catch {
      // Not cached yet.
    }

    await fs.mkdir(cacheDir, { recursive: true })
    const plist = await run('plutil', ['-extract', 'CFBundleIconFile', 'raw', '-o', '-', path.join(appPath, 'Contents', 'Info.plist')])
    const iconName = plist.code === 0 ? plist.stdout.trim() : ''

    if (iconName) {
      const icns = path.join(appPath, 'Contents', 'Resources', iconName.endsWith('.icns') ? iconName : `${iconName}.icns`)
      const sips = await run('sips', ['-s', 'format', 'png', '-Z', '256', icns, '--out', cacheFile], 10_000)

      if (sips.code === 0) {
        return fs.readFile(cacheFile).catch(() => null)
      }
    }

    const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'hermes-os-icon-'))

    try {
      const ql = await run('qlmanage', ['-t', '-s', '256', '-o', tmpDir, appPath], 15_000)

      if (ql.code !== 0) {
        return null
      }

      const produced = (await fs.readdir(tmpDir)).find(name => name.endsWith('.png'))

      if (!produced) {
        return null
      }

      await fs.copyFile(path.join(tmpDir, produced), cacheFile)

      return fs.readFile(cacheFile)
    } finally {
      await fs.rm(tmpDir, { recursive: true, force: true })
    }
  }

  async openIn(target: EditorTarget, targetPath: string): Promise<void> {
    const table: Record<EditorTarget, string[]> = {
      vscode: ['-a', 'Visual Studio Code', targetPath],
      cursor: ['-a', 'Cursor', targetPath],
      finder: ['-R', targetPath],
      terminal: ['-a', 'Terminal', targetPath]
    }
    const result = await run('open', table[target])

    if (result.code !== 0) {
      throw new Error(result.stderr.trim() || `open failed with code ${result.code}`)
    }
  }
}
