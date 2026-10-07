import { BrowserWindow, clipboard, ClipboardItem, dialog, ipcMain, type WebContents } from 'electron'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { parseManifest } from '../../shared/canvas/comp-format.ts'
import { CANVAS_IMAGE_EXTENSIONS, CONVERTED_IMAGE_EXTENSIONS, isProjectPath, PROJECT_EXTENSION, projectContaining } from '../../shared/canvas/files.ts'
import { type CanvasChangedEvent, type CanvasFetched, type CanvasPasted, type CanvasPresence, type CanvasProject, type CanvasRawImage, type CanvasSaveKind, type CanvasWrite, IPC } from '../../shared/ipc.ts'
import { assertWritable, normalizeUserPath } from '../ipc/fs.ts'
import { log } from '../log.ts'
import { convertToPng } from './convert.ts'
import { type PackageContents, PackageWatcher, readAsset, readPackage, writePackage } from './package-io.ts'
import { decodePng, encodePng, toChannels } from './png.ts'

const MAX_IMAGE_BYTES = 512 * 1024 * 1024

/**
 * A PNG as exact pixels when it decodes here (a browser canvas would round semi-transparent
 * colours), otherwise its bytes for the window to decode.
 */
function pixelsOrBytes(bytes: Uint8Array, channels: 1 | 4): CanvasRawImage | Uint8Array {
  try {
    const image = decodePng(bytes)

    return { width: image.width, height: image.height, channels, data: toChannels(image, channels) }
  } catch {
    return bytes
  }
}

/** A project Herald may read and write: a `.comp` folder in the home folder (or /tmp), outside protected places. */
export function projectPath(target: string): string {
  const dir = assertWritable(String(target)).replace(/[/\\]+$/, '')

  if (!isProjectPath(dir)) {
    throw new Error(`A Herald Canvas project is a folder whose name ends in ${PROJECT_EXTENSION}`)
  }

  return dir
}

/** An image Herald may open as a new project. */
function imagePath(target: string): string {
  const file = assertWritable(String(target))

  if (!CANVAS_IMAGE_EXTENSIONS.has(path.extname(file).toLowerCase())) {
    throw new Error(`Herald Canvas does not open ${path.extname(file) || 'this kind of file'}`)
  }

  return file
}

const toProject = (dir: string, contents: PackageContents): CanvasProject => ({ path: dir, manifest: contents.manifest, assets: contents.assets, digest: contents.digest })

interface Watch {
  watcher: PackageWatcher
  owner: WebContents
  dir: string
}

const watches = new Map<string, Watch>()

const SAVE_FILTERS: Record<CanvasSaveKind, Electron.FileFilter[]> = {
  project: [{ name: 'Herald Canvas project', extensions: ['comp'] }],
  png: [{ name: 'PNG image', extensions: ['png'] }],
  jpeg: [{ name: 'JPEG image', extensions: ['jpg', 'jpeg'] }],
  webp: [{ name: 'WebP image', extensions: ['webp'] }],
  psd: [{ name: 'Photoshop document', extensions: ['psd'] }]
}

const SAVE_EXTENSION: Record<CanvasSaveKind, string> = { project: '.comp', png: '.png', jpeg: '.jpg', webp: '.webp', psd: '.psd' }

function windowFor(sender: WebContents, fallback: () => BrowserWindow | null): BrowserWindow | undefined {
  return BrowserWindow.fromWebContents(sender) ?? fallback() ?? undefined
}

export function registerCanvasIpc(getWindow: () => BrowserWindow | null): void {
  ipcMain.handle(IPC.canvasPickOpen, async event => {
    const parent = windowFor(event.sender, getWindow)
    const options: Electron.OpenDialogOptions = {
      title: 'Open in Herald Canvas',
      defaultPath: path.join(os.homedir(), 'Pictures'),
      // On Linux a dialog picks files or folders, not both: pick a file inside a project to open it.
      properties: process.platform === 'darwin' ? ['openFile', 'openDirectory'] : ['openFile'],
      filters: [{ name: 'Projects and images', extensions: ['comp', 'json', ...[...CANVAS_IMAGE_EXTENSIONS].map(ext => ext.slice(1))] }]
    }
    const result = parent ? await dialog.showOpenDialog(parent, options) : await dialog.showOpenDialog(options)
    const picked = result.canceled ? null : result.filePaths[0]

    return picked ? (projectContaining(picked) ?? picked) : null
  })

  ipcMain.handle(IPC.canvasPickSave, async (event, kind: CanvasSaveKind, suggestedName: string) => {
    const parent = windowFor(event.sender, getWindow)
    const extension = SAVE_EXTENSION[kind] ?? '.png'
    const name = `${String(suggestedName || 'Untitled').replace(/[/\\]/g, '-')}${extension}`
    const options: Electron.SaveDialogOptions = { title: kind === 'project' ? 'Save project' : 'Export', defaultPath: path.join(os.homedir(), 'Pictures', name), filters: SAVE_FILTERS[kind] }
    const result = parent ? await dialog.showSaveDialog(parent, options) : await dialog.showSaveDialog(options)

    if (result.canceled || !result.filePath) {
      return null
    }

    return result.filePath.toLowerCase().endsWith(extension) ? result.filePath : `${result.filePath}${extension}`
  })

  ipcMain.handle(IPC.canvasRead, async (_event, target: string) => {
    const dir = projectPath(target)

    return toProject(dir, await readPackage(dir))
  })

  ipcMain.handle(IPC.canvasReadAsset, async (_event, target: string, name: string) => {
    const asset = String(name)

    return pixelsOrBytes(await readAsset(projectPath(target), asset), asset.endsWith('.mask.png') ? 1 : 4)
  })

  ipcMain.handle(IPC.canvasWrite, async (event, target: string, request: CanvasWrite) => {
    const dir = projectPath(target)
    const write = () => writePackage(dir, { manifest: parseManifest(request.manifest), assets: request.assets ?? {}, preview: request.preview })
    // This window's own save is not an outside change for it; other windows on the project still reload.
    const own = [...watches.values()].find(watch => watch.dir === dir && watch.owner === event.sender)

    return own ? own.watcher.ownWrite(write) : write()
  })

  ipcMain.handle(IPC.canvasReadImage, async (_event, target: string) => {
    const file = imagePath(target)
    const stat = await fs.stat(file)

    if (!stat.isFile() || stat.size > MAX_IMAGE_BYTES) {
      throw new Error(`${path.basename(file)} is too large to open`)
    }

    if (CONVERTED_IMAGE_EXTENSIONS.has(path.extname(file).toLowerCase())) {
      return pixelsOrBytes(await convertToPng(file), 4)
    }

    return pixelsOrBytes(new Uint8Array(await fs.readFile(file)), 4)
  })

  ipcMain.handle(IPC.canvasWriteFile, async (_event, target: string, data: Uint8Array | CanvasRawImage, ppi?: number) => {
    const file = assertWritable(String(target))
    const bytes = data instanceof Uint8Array ? data : encodePng(data as CanvasRawImage & { channels: 1 | 4 }, ppi)
    await fs.mkdir(path.dirname(file), { recursive: true })
    await fs.writeFile(file, bytes)

    return file
  })

  ipcMain.handle(IPC.canvasWatch, async (event, target: string, loaded?: string) => {
    const dir = projectPath(target)
    const owner = event.sender
    const watchId = crypto.randomUUID()
    const contents = await readPackage(dir)
    const send = (changed: PackageContents) => {
      if (!owner.isDestroyed()) {
        owner.send(IPC.canvasChanged, { watchId, project: toProject(dir, changed) } satisfies CanvasChangedEvent)
      }
    }
    // Compared with the version the window loaded, so a save landing between its read and this watch still arrives.
    const watcher = new PackageWatcher(dir, typeof loaded === 'string' && loaded ? loaded : contents.digest, send)
    watcher.start()

    if (typeof loaded === 'string' && loaded && loaded !== contents.digest) {
      setTimeout(() => void watcher.check(), 0)
    }
    watches.set(watchId, { watcher, owner, dir })
    owner.once('destroyed', () => {
      watcher.stop()
      watches.delete(watchId)
    })
    log('canvas', `watching ${dir}`)

    return watchId
  })

  ipcMain.handle(IPC.canvasUnwatch, (_event, watchId: string) => {
    watches.get(watchId)?.watcher.stop()
    watches.delete(watchId)
  })

  ipcMain.handle(IPC.canvasExists, async (_event, target: string) => {
    try {
      const stat = await fs.stat(normalizeUserPath(String(target)))

      return stat.isDirectory() ? 'directory' : 'file'
    } catch {
      return null
    }
  })

  ipcMain.handle(IPC.canvasFetch, async (_event, address: string) => fetchImage(String(address)))

  ipcMain.on(IPC.canvasReport, (event, report: Omit<CanvasPresence, 'at'> & { focused?: boolean }) => {
    const id = event.sender.id
    const known = presence.get(id)

    if (!known) {
      event.sender.once('destroyed', () => presence.delete(id))
    }

    presence.set(id, { active: report.active ?? null, documents: Array.isArray(report.documents) ? report.documents : [], at: report.focused || !known ? Date.now() : known.at })
  })

  ipcMain.handle(IPC.canvasPresence, () => [...presence.values()].sort((a, b) => b.at - a.at))

  ipcMain.handle(IPC.canvasCopyImage, async (_event, image: CanvasRawImage) => {
    const png = encodePng({ width: image.width, height: image.height, channels: image.channels === 1 ? 1 : 4, data: image.data })
    await clipboard.write([new ClipboardItem({ 'image/png': new Blob([new Uint8Array(png)], { type: 'image/png' }) })])
    // Read back the way Paste reads, so the comparison holds however the system stores images.
    ownCopy = digestOf(await clipboardImage())
  })

  ipcMain.handle(IPC.canvasPasteImage, async (): Promise<CanvasPasted | null> => {
    const bytes = await clipboardImage()

    if (!bytes) {
      return null
    }

    return { image: pixelsOrBytes(bytes, 4), own: ownCopy !== null && digestOf(bytes) === ownCopy }
  })
}

/** A digest of what Herald Canvas last put on the clipboard, to tell its own copies from other apps'. */
let ownCopy: string | null = null

const digestOf = (bytes: Uint8Array | null): string | null => (bytes ? crypto.createHash('sha256').update(bytes).digest('hex') : null)

/** The clipboard's image as PNG bytes, or null when it holds none. */
async function clipboardImage(): Promise<Uint8Array | null> {
  for (const item of await clipboard.read()) {
    const type = item.types.find((entry) => entry === 'image/png') ?? item.types.find((entry) => entry.startsWith('image/'))

    if (type) {
      const blob = (await item.getType(type)) as Blob
      const bytes = new Uint8Array(await blob.arrayBuffer())

      if (bytes.byteLength > MAX_IMAGE_BYTES) {
        throw new Error('The image on the clipboard is too large')
      }

      return bytes
    }
  }

  return null
}

/** What each Canvas window has open, by its web contents. */
const presence = new Map<number, CanvasPresence>()

const MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

/** An image from the web for a new layer: http(s) only, limited in size and time. */
export async function fetchImage(address: string): Promise<CanvasFetched> {
  const url = new URL(address)

  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new Error('Images come from http or https addresses')
  }

  const response = await fetch(url, { redirect: 'follow', signal: AbortSignal.timeout(60_000) })

  if (!response.ok || !response.body) {
    throw new Error(`${url.host} answered ${response.status}`)
  }

  const declared = Number(response.headers.get('content-length') ?? 0)

  if (declared > MAX_DOWNLOAD_BYTES) {
    throw new Error('That image is larger than 100 MB')
  }

  const chunks: Uint8Array[] = []
  let total = 0
  const reader = response.body.getReader()

  for (;;) {
    const { done, value } = await reader.read()

    if (done) {
      break
    }

    total += value.byteLength

    if (total > MAX_DOWNLOAD_BYTES) {
      await reader.cancel()
      throw new Error('That image is larger than 100 MB')
    }

    chunks.push(value)
  }

  const bytes = new Uint8Array(total)
  let offset = 0

  for (const chunk of chunks) {
    bytes.set(chunk, offset)
    offset += chunk.byteLength
  }

  const type = response.headers.get('content-type') ?? ''
  const svg = type.includes('svg') || url.pathname.toLowerCase().endsWith('.svg')

  return { image: svg ? bytes : pixelsOrBytes(bytes, 4), svg }
}
