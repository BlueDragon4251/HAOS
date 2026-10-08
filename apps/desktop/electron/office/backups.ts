import fs from 'node:fs/promises'
import path from 'node:path'
import { log } from '../log.ts'

/*
 * The first time Herald saves over an Office file in a session, the file as it was goes into
 * `office-backups/<date>/<name>` under the Herald OS data folder, so a save that kept less than the
 * file had can be undone by hand. Backups are kept for a month and to a total size, oldest out first.
 */

export interface BackupLimits {
  /** A file larger than this is not copied. */
  fileBytes: number
  totalBytes: number
  days: number
}

export const BACKUP_LIMITS: BackupLimits = { fileBytes: 256 * 1024 * 1024, totalBytes: 2 * 1024 * 1024 * 1024, days: 30 }

const DAY_MS = 24 * 60 * 60 * 1000

/** The day folder a backup taken at `now` goes in (local time, YYYY-MM-DD). */
export function dayFolder(now: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0')

  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** `name` or, when that is taken, "name (2).ext", "name (3).ext" and so on. */
export function freeName(name: string, taken: ReadonlySet<string>): string {
  if (!taken.has(name)) {
    return name
  }

  const extension = path.extname(name)
  const stem = name.slice(0, name.length - extension.length)

  for (let n = 2; ; n++) {
    const candidate = `${stem} (${n})${extension}`

    if (!taken.has(candidate)) {
      return candidate
    }
  }
}

export interface BackupEntry {
  path: string
  size: number
  modifiedAt: number
}

/** The backups to remove: those older than the limit, then the oldest until the rest fit the total. */
export function prunePlan(entries: readonly BackupEntry[], limits: Pick<BackupLimits, 'totalBytes' | 'days'>, now: number): string[] {
  const oldestFirst = [...entries].sort((a, b) => a.modifiedAt - b.modifiedAt)
  const remove = new Set(oldestFirst.filter((entry) => now - entry.modifiedAt > limits.days * DAY_MS).map((entry) => entry.path))
  let total = oldestFirst.filter((entry) => !remove.has(entry.path)).reduce((sum, entry) => sum + entry.size, 0)

  for (const entry of oldestFirst) {
    if (total <= limits.totalBytes) {
      break
    }

    if (!remove.has(entry.path)) {
      remove.add(entry.path)
      total -= entry.size
    }
  }

  return [...remove]
}

async function listBackups(root: string): Promise<BackupEntry[]> {
  const entries: BackupEntry[] = []

  for (const day of await fs.readdir(root, { withFileTypes: true }).catch(() => [])) {
    if (!day.isDirectory()) {
      continue
    }

    const folder = path.join(root, day.name)

    for (const file of await fs.readdir(folder, { withFileTypes: true }).catch(() => [])) {
      if (file.isFile()) {
        const stat = await fs.stat(path.join(folder, file.name)).catch(() => null)

        if (stat) {
          entries.push({ path: path.join(folder, file.name), size: stat.size, modifiedAt: stat.mtimeMs })
        }
      }
    }
  }

  return entries
}

export class OfficeBackups {
  /** Files backed up this session (the first save over each is the one that loses the original). */
  private readonly done = new Set<string>()

  constructor(
    private readonly root: string,
    private readonly limits: BackupLimits = BACKUP_LIMITS,
    private readonly now: () => Date = () => new Date()
  ) {}

  /** Copy `file` as it is now, once a session; resolves with the copy's path, or null when none was made. */
  async before(file: string): Promise<string | null> {
    if (this.done.has(file)) {
      return null
    }

    const stat = await fs.stat(file).catch(() => null)

    if (!stat?.isFile()) {
      return null
    }

    this.done.add(file)

    if (stat.size > this.limits.fileBytes) {
      log('office', `not backing up ${path.basename(file)}: ${Math.round(stat.size / 1024 / 1024)} MB is over the limit`)

      return null
    }

    const folder = path.join(this.root, dayFolder(this.now()))
    await fs.mkdir(folder, { recursive: true })
    const target = path.join(folder, freeName(path.basename(file), new Set(await fs.readdir(folder))))
    await fs.copyFile(file, target)
    // The copy is dated now, so pruning keeps backups by when they were taken.
    const taken = this.now()
    await fs.utimes(target, taken, taken).catch(() => {})
    void this.prune()

    return target
  }

  async prune(): Promise<void> {
    const remove = prunePlan(await listBackups(this.root), this.limits, this.now().getTime())

    for (const file of remove) {
      await fs.rm(file, { force: true })
    }

    for (const day of await fs.readdir(this.root).catch(() => [])) {
      await fs.rmdir(path.join(this.root, day)).catch(() => {})
    }
  }
}
