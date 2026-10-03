import { describe, expect, it, vi } from 'vitest'
import { DarwinPlatform, parseDf, parsePmset, parsePs, parseVmStat, parseWifiDevice, parseWifiSummary } from './darwin.ts'

const commands = vi.hoisted(() => ({ outputs: new Map<string, string>(), calls: [] as string[] }))

vi.mock('./exec.ts', () => ({
  MISSING_BINARY: 127,
  run: vi.fn(async (command: string, args: string[]) => {
    const line = [command, ...args].join(' ')
    commands.calls.push(line)

    return { stdout: commands.outputs.get(line) ?? '', stderr: '', code: 0 }
  }),
  runBuffer: vi.fn()
}))

const PORTS = '\nHardware Port: Ethernet Adapter (en3)\nDevice: en3\nEthernet Address: 7a:00:00:00:00:01\n\nHardware Port: Wi-Fi\nDevice: en0\nEthernet Address: 7a:00:00:00:00:02\n'
const SUMMARY = '<dictionary> {\n  BSSID : <redacted>\n  InterfaceType : WiFi\n  LinkStatusActive : TRUE\n  SSID : Cafe Guest\n}\n'

describe('Wi-Fi status', () => {
  it('finds the Wi-Fi device among the hardware ports', () => {
    expect(parseWifiDevice(PORTS)).toBe('en0')
    expect(parseWifiDevice('Hardware Port: Ethernet\nDevice: en5\n')).toBeUndefined()
  })

  it('reads the link and the SSID, and drops an SSID macOS redacted', () => {
    expect(parseWifiSummary(SUMMARY, 'en0')).toEqual({ connected: true, ssid: 'Cafe Guest', interface: 'en0' })
    expect(parseWifiSummary(SUMMARY.replace('SSID : Cafe Guest', 'SSID : <redacted>'), 'en0').ssid).toBeUndefined()
    expect(parseWifiSummary('  LinkStatusActive : FALSE\n', 'en0')).toEqual({ connected: false, ssid: undefined, interface: 'en0' })
  })

  it('never runs system_profiler, which scans for networks on every call', async () => {
    commands.outputs.set('route -n get default', '   route to: default\n  interface: en0\n')
    commands.outputs.set('ipconfig getifaddr en0', '192.168.1.20\n')
    commands.outputs.set('networksetup -listallhardwareports', PORTS)
    commands.outputs.set('ipconfig getsummary en0', SUMMARY)

    expect(await new DarwinPlatform().networkStatus()).toEqual({ online: true, defaultInterface: 'en0', ipv4: '192.168.1.20', wifi: { connected: true, ssid: 'Cafe Guest', interface: 'en0' } })
    expect(commands.calls.filter(line => line.startsWith('system_profiler'))).toEqual([])
  })
})

describe('darwin parsers', () => {
  it('derives used memory from active + wired + compressor pages', () => {
    const text = 'Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 100.\nPages active: 10.\nPages wired down: 5.\nPages occupied by compressor: 1.\n'
    expect(parseVmStat(text)).toEqual({ pageSize: 16384, usedBytes: 16 * 16384 })
    expect(parseVmStat('garbage')).toBeNull()
  })

  it('keeps the root volume and external volumes, drops hidden APFS volumes', () => {
    const df = ['Filesystem 1024-blocks Used Available Capacity Mounted on', '/dev/disk3s1s1 1000 400 600 40% /', 'devfs 1 1 0 100% /dev', '/dev/disk3s6 1000 10 990 1% /System/Volumes/VM', '/dev/disk5s1 2000 500 1500 25% /Volumes/Backup Drive'].join('\n')
    const disks = parseDf(df)
    expect(disks.map(d => d.mount)).toEqual(['/', '/Volumes/Backup Drive'])
    expect(disks[1]).toMatchObject({ total: 2000 * 1024, used: 500 * 1024, free: 1500 * 1024 })
    // Root: APFS "Used" (400) is only the system volume; usage is derived from what is still available.
    expect(disks[0]).toMatchObject({ total: 1000 * 1024, used: 400 * 1024, free: 600 * 1024 })
  })

  it('reads battery percentage and charging state', () => {
    expect(parsePmset("Now drawing from 'AC Power'\n -InternalBattery-0 (id=123)\t85%; charging; 0:45 remaining present: true")).toEqual({ present: true, percent: 85, charging: true })
    expect(parsePmset("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=123)\t42%; discharging; 3:10 remaining present: true")).toEqual({ present: true, percent: 42, charging: false })
    expect(parsePmset('Now drawing from AC Power')).toEqual({ present: false })
  })

  it('parses ps rows including commands with spaces', () => {
    const rows = parsePs('  512     1 sam   12.5  0.3   204800 /Applications/Visual Studio Code.app/Contents/MacOS/Electron\n')
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ pid: 512, ppid: 1, user: 'sam', cpuPercent: 12.5, rssBytes: 204800 * 1024, name: 'Electron' })
  })
})
