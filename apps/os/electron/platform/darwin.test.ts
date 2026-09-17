import { describe, expect, it } from 'vitest'
import { parseDf, parsePmset, parsePs, parseVmStat } from './darwin.ts'

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
