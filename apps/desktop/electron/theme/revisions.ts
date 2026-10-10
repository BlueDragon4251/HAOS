/** Content-addressed theme bundles. Publish the complete bundle before its index. */
import { createHash, randomUUID } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { type ThemeSpec, validateTheme } from '../../shared/theme.ts'

const NAME = /^[a-z0-9][a-z0-9-]{0,39}$/
const REVISION = /^[a-f0-9]{64}$/
const IMAGE_LIMIT = 25 * 1024 * 1024

export interface ThemeBundle {
  spec: ThemeSpec
  dir: string
  revision: string
}

/** Open bounded regular files without following the final component. */
export function readThemeFile(file: string, limit: number): Buffer {
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW)
  try {
    const info = fs.fstatSync(fd)
    if (!info.isFile() || info.nlink !== 1 || info.size > limit) throw new Error('Unsafe theme file')
    const buffer = Buffer.alloc(Math.min(info.size + 1, limit + 1))
    const count = fs.readSync(fd, buffer, 0, buffer.length, 0)
    if (count !== info.size) throw new Error('Theme file changed during import')
    return buffer.subarray(0, count)
  } finally {
    fs.closeSync(fd)
  }
}

function directory(dir: string, create = false): void {
  if (create) fs.mkdirSync(dir, { mode: 0o700, recursive: true })
  const info = fs.lstatSync(dir)
  if (!info.isDirectory() || info.mode & 0o022) throw new Error('Unsafe theme bundle directory')
}

function syncDirectory(dir: string): void {
  const fd = fs.openSync(dir, fs.constants.O_RDONLY)
  try { fs.fsyncSync(fd) } finally { fs.closeSync(fd) }
}

function writeFile(file: string, bytes: Buffer): void {
  const fd = fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, 0o600)
  try { fs.writeFileSync(fd, bytes); fs.fsyncSync(fd) } finally { fs.closeSync(fd) }
}

function digest(manifest: Buffer, image?: Buffer): string {
  return createHash('sha256').update(manifest).update('\0').update(image ?? Buffer.alloc(0)).digest('hex')
}

export class ThemeRevisions {
  constructor(readonly root: string, readonly anchor: string) {}

  private base(name: string, create = false): string {
    if (!NAME.test(name)) throw new Error('Invalid theme name')
    // The root's immediate ancestors belong to the theme store, not an import.
    // Reject redirection before mkdir follows any existing parent component.
    const relative = path.relative(this.anchor, this.root)
    if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Theme store escapes its home')
    for (let parent = this.root; ; parent = path.dirname(parent)) {
      if (fs.existsSync(parent) || fs.lstatSync(parent, { throwIfNoEntry: false })) directory(parent)
      if (parent === this.anchor) break
    }
    directory(this.root, create)
    const base = path.join(this.root, name)
    directory(base, create)
    return base
  }

  read(name: string, revision?: string): ThemeBundle {
    const base = this.base(name)
    let selected = revision
    if (selected === undefined) {
      const index = JSON.parse(readThemeFile(path.join(base, 'current.json'), 1024).toString('utf8')) as Record<string, unknown>
      if (Object.keys(index).sort().join(',') !== 'revision,schema' || index.schema !== 1 || typeof index.revision !== 'string') throw new Error('Invalid theme index')
      selected = index.revision
    }
    if (!REVISION.test(selected)) throw new Error('Invalid theme revision')
    const dir = path.join(base, selected)
    directory(dir)
    const manifest = readThemeFile(path.join(dir, 'theme.json'), 65536)
    const spec = JSON.parse(manifest.toString('utf8')) as ThemeSpec
    const problem = validateTheme(spec)
    if (problem || spec.name !== name) throw new Error(problem || 'Theme identity changed')
    const image = spec.wallpaper && spec.wallpaper !== 'default' ? readThemeFile(path.join(dir, spec.wallpaper), IMAGE_LIMIT) : undefined
    if (digest(manifest, image) !== selected) throw new Error('Theme revision failed its checksum')
    return { spec, dir, revision: selected }
  }

  publish(spec: ThemeSpec, image?: Buffer): ThemeBundle {
    const problem = validateTheme(spec)
    if (problem) throw new Error(problem)
    const needsImage = Boolean(spec.wallpaper && spec.wallpaper !== 'default')
    if (needsImage !== Boolean(image) || (image && (!image.length || image.length > IMAGE_LIMIT))) throw new Error('Theme wallpaper is missing or oversized')
    const manifest = Buffer.from(`${JSON.stringify(spec, null, 2)}\n`)
    if (manifest.length > 65536) throw new Error('Theme manifest is oversized')
    const revision = digest(manifest, image)
    const base = this.base(spec.name, true)
    const target = path.join(base, revision)
    const scratch = path.join(base, `.stage-${randomUUID()}`)
    const index = path.join(base, `.index-${randomUUID()}`)
    try {
      if (!fs.existsSync(target)) {
        fs.mkdirSync(scratch, { mode: 0o700 })
        writeFile(path.join(scratch, 'theme.json'), manifest)
        if (image) writeFile(path.join(scratch, spec.wallpaper as string), image)
        syncDirectory(scratch)
        fs.renameSync(scratch, target)
        syncDirectory(base)
      }
      // Existing content is verified too; never repair an altered revision by
      // overwriting it or point the current index at a partial bundle.
      const bundle = this.read(spec.name, revision)
      writeFile(index, Buffer.from(`${JSON.stringify({ schema: 1, revision })}\n`))
      fs.renameSync(index, path.join(base, 'current.json'))
      syncDirectory(base)
      return bundle
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true })
      fs.rmSync(index, { force: true })
    }
  }

  names(): string[] {
    try {
      directory(this.root)
      return fs.readdirSync(this.root).filter(name => NAME.test(name)).sort()
    } catch { return [] }
  }

  history(name: string): ThemeBundle[] {
    const base = this.base(name)
    const result: ThemeBundle[] = []
    for (const revision of fs.readdirSync(base).filter(value => REVISION.test(value)).sort()) {
      try { result.push(this.read(name, revision)) } catch { /* Corrupt revisions are never offered. */ }
    }
    return result
  }
}
