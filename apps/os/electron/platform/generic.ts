import os from 'node:os'
import type { InstalledApp, ProcessInfo, SystemInfo, SystemStats } from '../../shared/ipc.ts'
import { type EditorTarget, type HostPlatform, HostNotSupported } from './types.ts'

/**
 * Placeholder for win32 / linux: enough for the shell to boot and show honest "not yet" states.
 * Real implementations land per docs/ROADMAP.md.
 */
export class GenericPlatform implements HostPlatform {
  async systemInfo(): Promise<SystemInfo> {
    const cpus = os.cpus()

    return {
      hostname: os.hostname(),
      platform: process.platform,
      arch: process.arch,
      osName: os.type(),
      osVersion: os.release(),
      cpuModel: cpus[0]?.model ?? 'unknown',
      cpuCount: cpus.length,
      totalMemory: os.totalmem(),
      userName: os.userInfo().username,
      homeDir: os.homedir()
    }
  }

  async sampleStats(): Promise<SystemStats> {
    const total = os.totalmem()
    const free = os.freemem()

    return {
      sampledAt: Date.now(),
      cpuPercent: 0,
      loadAverage: os.loadavg() as [number, number, number],
      memoryTotal: total,
      memoryUsed: total - free,
      memoryFree: free,
      uptimeSeconds: os.uptime(),
      disks: [],
      battery: { present: false }
    }
  }

  async listProcesses(): Promise<ProcessInfo[]> {
    return []
  }

  async listInstalledApps(): Promise<InstalledApp[]> {
    return []
  }

  async appIcon(): Promise<Buffer | null> {
    return null
  }

  async openIn(target: EditorTarget): Promise<void> {
    throw new HostNotSupported(`openIn(${target})`)
  }
}
