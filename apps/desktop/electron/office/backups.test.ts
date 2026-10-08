import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { dayFolder, freeName, OfficeBackups, prunePlan } from './backups.ts'

const DAY = 24 * 60 * 60 * 1000
let root = ''

afterEach(async () => {
  await fs.rm(root, { recursive: true, force: true })
})

describe('dayFolder and freeName', () => {
  it('names the day and finds a free name beside the taken ones', () => {
    expect(dayFolder(new Date(2026, 9, 8, 21, 5))).toBe('2026-10-08')
    expect(freeName('Plan.docx', new Set())).toBe('Plan.docx')
    expect(freeName('Plan.docx', new Set(['Plan.docx', 'Plan (2).docx']))).toBe('Plan (3).docx')
    expect(freeName('README', new Set(['README']))).toBe('README (2)')
  })
})

describe('prunePlan', () => {
  const now = 100 * DAY

  it('removes backups past the age limit', () => {
    const entries = [
      { path: 'old', size: 1, modifiedAt: now - 31 * DAY },
      { path: 'new', size: 1, modifiedAt: now - DAY }
    ]

    expect(prunePlan(entries, { totalBytes: 100, days: 30 }, now)).toEqual(['old'])
  })

  it('removes the oldest until the rest fit the total', () => {
    const entries = [
      { path: 'c', size: 50, modifiedAt: now - 1 },
      { path: 'a', size: 50, modifiedAt: now - 3 },
      { path: 'b', size: 50, modifiedAt: now - 2 }
    ]

    expect(prunePlan(entries, { totalBytes: 100, days: 30 }, now)).toEqual(['a'])
    expect(prunePlan(entries, { totalBytes: 40, days: 30 }, now)).toEqual(['a', 'b', 'c'])
  })
})

describe('OfficeBackups', () => {
  it('copies a file once a session, into the day folder, beside earlier backups of the same name', async () => {
    root = await fs.mkdtemp(path.join(os.tmpdir(), 'office-backups-'))
    const file = path.join(root, 'work', 'Budget.csv')
    await fs.mkdir(path.dirname(file))
    await fs.writeFile(file, 'original')
    const day = new Date(2026, 9, 8)
    const backups = new OfficeBackups(path.join(root, 'backups'), { fileBytes: 1024, totalBytes: 1024 * 1024, days: 30 }, () => day)

    const first = await backups.before(file)
    expect(first).toBe(path.join(root, 'backups', '2026-10-08', 'Budget.csv'))
    expect(await fs.readFile(first!, 'utf8')).toBe('original')

    await fs.writeFile(file, 'saved by Herald')
    expect(await backups.before(file)).toBeNull()

    const later = new OfficeBackups(path.join(root, 'backups'), { fileBytes: 1024, totalBytes: 1024 * 1024, days: 30 }, () => day)
    expect(await later.before(file)).toBe(path.join(root, 'backups', '2026-10-08', 'Budget (2).csv'))
  })

  it('does not copy a missing file or one over the size limit', async () => {
    root = await fs.mkdtemp(path.join(os.tmpdir(), 'office-backups-'))
    const big = path.join(root, 'big.csv')
    await fs.writeFile(big, 'x'.repeat(2048))
    const backups = new OfficeBackups(path.join(root, 'backups'), { fileBytes: 1024, totalBytes: 1024 * 1024, days: 30 })

    expect(await backups.before(big)).toBeNull()
    expect(await backups.before(path.join(root, 'missing.csv'))).toBeNull()
  })
})
