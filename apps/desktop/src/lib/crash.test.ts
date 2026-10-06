import { describe, expect, it } from 'vitest'
import type { CrashReport } from '../../shared/ipc.ts'
import { crashPrompt, crashReference, findCrash } from './crash.ts'

const mac: CrashReport = { id: 'ips:1', app: 'Safari', pid: 42, reason: 'EXC_BAD_ACCESS (SIGSEGV)', reportPath: '/Users/me/Library/Logs/DiagnosticReports/Safari.ips', at: 1_000_000, source: 'macos' }
const linux: CrashReport = { id: 'coredump:7:1', app: 'firefox', pid: 7, exe: '/usr/bin/firefox', reason: 'SIGSEGV', at: 1_000_000, source: 'coredump' }

describe('crashPrompt', () => {
  it('points Hermes at the report file on macOS', () => {
    const text = crashPrompt(mac, 1_000_000 + 3 * 60_000)

    expect(text).toContain('Safari crashed 3 minutes ago (EXC_BAD_ACCESS (SIGSEGV)).')
    expect(text).toContain('The crash report is /Users/me/Library/Logs/DiagnosticReports/Safari.ips.')
    expect(text).toContain('report=/Users/me/Library/Logs/DiagnosticReports/Safari.ips')
    expect(text).toContain('diagnose-crash skill')
  })

  it('points Hermes at the core dump on Linux', () => {
    const text = crashPrompt(linux, 1_000_000)

    expect(text).toContain('firefox crashed just now (SIGSEGV).')
    expect(text).toContain('core dump: pid 7, /usr/bin/firefox')
    expect(crashReference(linux)).toBe('7')
  })
})

describe('findCrash', () => {
  const reports = [linux, mac]

  it('finds by id, name or pid, and "that" means the newest', () => {
    expect(findCrash(reports, 'ips:1')).toBe(mac)
    expect(findCrash(reports, 'safari')).toBe(mac)
    expect(findCrash(reports, '7')).toBe(linux)
    expect(findCrash(reports, 'that')).toBe(linux)
    expect(findCrash(reports)).toBe(linux)
    expect(findCrash(reports, 'mail')).toBeUndefined()
  })
})
