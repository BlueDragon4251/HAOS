import { describe, expect, it } from 'vitest'
import { isDarwinUserMount, parseDf, parsePs } from './posix.ts'

const DF = ['Filesystem 1024-blocks Used Available Capacity Mounted on', '/dev/nvme0n1p2 1000 400 600 40% /', 'tmpfs 100 1 99 1% /run', '/dev/nvme0n1p1 500 50 450 10% /boot/efi', '/dev/sdb1 2000 500 1500 25% /media/sam/Backup Drive'].join('\n')

describe('posix parsers', () => {
  it('parses every df -kP row when given a permissive predicate', () => {
    const disks = parseDf(DF, () => true)
    expect(disks.map(d => d.mount)).toEqual(['/', '/run', '/boot/efi', '/media/sam/Backup Drive'])
    expect(disks[3]).toEqual({ mount: '/media/sam/Backup Drive', total: 2000 * 1024, used: 500 * 1024, free: 1500 * 1024 })
  })

  it('defaults to the macOS mount rule so darwin callers are unchanged', () => {
    expect(parseDf(DF).map(d => d.mount)).toEqual(['/'])
    expect(isDarwinUserMount('/Volumes/Backup')).toBe(true)
    expect(isDarwinUserMount('/Volumes/.timemachine')).toBe(false)
    expect(isDarwinUserMount('/home')).toBe(false)
  })

  it('skips rows with a zero or unparsable size', () => {
    expect(parseDf('header\nnone 0 0 0 - /proc\nfoo bar baz qux 1% /x', () => true)).toEqual([])
  })

  it('parses Linux ps -eo rows (bare comm) as well as full command paths', () => {
    const rows = parsePs(['  512     1 sam   12.5  0.3   204800 /usr/lib/firefox/firefox', ' 1234   512 root     0.0  0.1     1024 kworker/u8:1', 'garbage line'].join('\n'))
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ pid: 512, ppid: 1, user: 'sam', cpuPercent: 12.5, memPercent: 0.3, rssBytes: 204800 * 1024, name: 'firefox' })
    expect(rows[1]).toMatchObject({ pid: 1234, user: 'root', command: 'kworker/u8:1', name: 'u8:1' })
  })
})
