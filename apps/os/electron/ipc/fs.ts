import { ipcMain, shell } from 'electron'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { type DirEntry, type FilePreview, IPC } from '../../shared/ipc.ts'
import { type EditorTarget, hostPlatform } from '../platform/index.ts'

const TEXT_LIMIT = 2 * 1024 * 1024
const IMAGE_LIMIT = 24 * 1024 * 1024
const IMAGE_MIME: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.bmp': 'image/bmp',
  '.ico': 'image/x-icon'
}
const TEXT_EXTENSIONS = new Set([
  '.txt', '.md', '.markdown', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.env', '.log',
  '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.py', '.rb', '.go', '.rs', '.java', '.kt', '.swift', '.c', '.h',
  '.cpp', '.hpp', '.cs', '.sh', '.zsh', '.bash', '.fish', '.sql', '.html', '.css', '.scss', '.xml', '.csv', '.plist',
  '.gitignore', '.lock', '.mk', '.cmake', '.gradle', '.properties', '.tf', '.vue', '.svelte', '.astro', '.graphql'
])

/** Only absolute paths; `~` expands to home. Relative paths are refused so the renderer cannot probe cwd. */
export function normalizeUserPath(input: string): string {
  const expanded = input === '~' || input.startsWith('~/') ? path.join(os.homedir(), input.slice(1)) : input

  if (!path.isAbsolute(expanded)) {
    throw new Error(`path must be absolute: ${input}`)
  }

  return path.normalize(expanded)
}

async function readDir(target: string): Promise<DirEntry[]> {
  const dir = normalizeUserPath(target)
  const dirents = await fs.readdir(dir, { withFileTypes: true })
  const entries = await Promise.all(
    dirents.map(async dirent => {
      const full = path.join(dir, dirent.name)
      let size = 0
      let modifiedAt = 0
      let kind: DirEntry['kind'] = dirent.isDirectory() ? 'directory' : dirent.isFile() ? 'file' : dirent.isSymbolicLink() ? 'symlink' : 'other'

      try {
        const stat = await fs.stat(full)
        size = stat.size
        modifiedAt = stat.mtimeMs

        if (kind === 'symlink') {
          kind = stat.isDirectory() ? 'directory' : 'file'
        }
      } catch {
        // Broken symlink or permission denied: keep the dirent-derived kind.
      }

      return {
        name: dirent.name,
        path: full,
        kind,
        size,
        modifiedAt,
        hidden: dirent.name.startsWith('.'),
        extension: path.extname(dirent.name).toLowerCase()
      }
    })
  )

  entries.sort((a, b) => {
    if (a.kind !== b.kind && (a.kind === 'directory' || b.kind === 'directory')) {
      return a.kind === 'directory' ? -1 : 1
    }

    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true })
  })

  return entries
}

async function readFile(target: string): Promise<FilePreview> {
  const file = normalizeUserPath(target)
  const stat = await fs.stat(file)

  if (stat.isDirectory()) {
    return { path: file, kind: 'directory', size: 0 }
  }

  const ext = path.extname(file).toLowerCase()
  const imageMime = IMAGE_MIME[ext]

  if (imageMime) {
    if (stat.size > IMAGE_LIMIT) {
      return { path: file, kind: 'too-large', size: stat.size, mime: imageMime }
    }

    const data = await fs.readFile(file)

    return { path: file, kind: 'image', size: stat.size, mime: imageMime, content: `data:${imageMime};base64,${data.toString('base64')}` }
  }

  const looksText = TEXT_EXTENSIONS.has(ext) || ext === '' || /^\.[a-z0-9]{1,6}rc$/.test(ext)
  const handle = await fs.open(file, 'r')

  try {
    const probe = Buffer.alloc(Math.min(8192, stat.size))
    await handle.read(probe, 0, probe.length, 0)
    const binary = !looksText && probe.includes(0)

    if (binary || (!looksText && probe.includes(0))) {
      return { path: file, kind: 'binary', size: stat.size }
    }

    const readable = Math.min(stat.size, TEXT_LIMIT)
    const buffer = Buffer.alloc(readable)
    await handle.read(buffer, 0, readable, 0)

    return { path: file, kind: 'text', size: stat.size, content: buffer.toString('utf8'), truncated: stat.size > TEXT_LIMIT }
  } finally {
    await handle.close()
  }
}

export function registerFsIpc(): void {
  ipcMain.handle(IPC.fsHome, () => os.homedir())
  ipcMain.handle(IPC.fsReadDir, (_event, target: string) => readDir(target))
  ipcMain.handle(IPC.fsReadFile, (_event, target: string) => readFile(target))
  ipcMain.handle(IPC.fsReveal, (_event, target: string) => {
    shell.showItemInFolder(normalizeUserPath(target))
  })
  ipcMain.handle(IPC.fsOpenPath, async (_event, target: string) => {
    const error = await shell.openPath(normalizeUserPath(target))

    if (error) {
      throw new Error(error)
    }
  })
  ipcMain.handle(IPC.fsOpenIn, (_event, editor: EditorTarget, target: string) => hostPlatform().openIn(editor, normalizeUserPath(target)))
}
