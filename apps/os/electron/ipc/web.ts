import { BrowserWindow, ipcMain, session, type WebContents, WebContentsView } from 'electron'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { IPC, type WebOpenOptions, type WebViewBounds, type WebViewEvent } from '../../shared/ipc.ts'
import { isViewable } from '../../shared/viewer.ts'
import { log } from '../log.ts'

/*
 * Embedded web pages. Hermes OS is a whole environment, so a web page (the provider sign-in portal,
 * for now) opens inside it rather than in the system browser. In desktop mode the page is a
 * `WebContentsView` layered over the shell window; the renderer's window manager draws the frame and
 * streams the content rect here so the page sits exactly inside it. In panels mode (niri) there is
 * no single desktop window, so the page gets a real compositor window instead.
 *
 * The guest is locked down: sandboxed, isolated, no Node, no preload, its own storage partition with
 * every permission denied, http(s) only, popups denied (same-origin ones navigate the same view).
 */

const PARTITION = 'persist:hermes-web'
const DETACHED_SIZE = { width: 1000, height: 720 }

const isHttp = (url: string): boolean => /^https?:\/\//i.test(url)

interface EmbeddedView {
  kind: 'view'
  id: string
  view: WebContentsView
  host: BrowserWindow
  owner: WebContents
}

interface DetachedView {
  kind: 'window'
  id: string
  win: BrowserWindow
  owner: WebContents
}

type Entry = EmbeddedView | DetachedView

const GUEST_PREFERENCES: Electron.WebPreferences = {
  sandbox: true,
  contextIsolation: true,
  nodeIntegration: false,
  nodeIntegrationInWorker: false,
  nodeIntegrationInSubFrames: false,
  webSecurity: true,
  allowRunningInsecureContent: false,
  webviewTag: false,
  plugins: false,
  spellcheck: false,
  partition: PARTITION
}

/** Local files: same lockdown, own partition, plus Chromium's PDF viewer plugin. */
const VIEWER_PREFERENCES: Electron.WebPreferences = { ...GUEST_PREFERENCES, plugins: true, partition: 'persist:hermes-viewer' }

/** Studio previews of the site Hermes is building: same lockdown, own partition so dev-server state never mixes with browsing. */
const PREVIEW_PARTITION = 'persist:hermes-preview'
const PREVIEW_PREFERENCES: Electron.WebPreferences = { ...GUEST_PREFERENCES, partition: PREVIEW_PARTITION }

/** A preview may show http(s) pages and local files inside the project folder, nothing else. */
function previewAllows(url: string, root: string | null): boolean {
  if (isHttp(url)) {
    return true
  }

  if (!root || !url.startsWith('file://')) {
    return false
  }

  try {
    const file = path.normalize(decodeURIComponent(new URL(url).pathname))

    return file === root || file.startsWith(root + path.sep)
  } catch {
    return false
  }
}

function resolveHomePath(raw: string): string {
  return path.resolve(raw.replace(/^~(?=\/|$)/, os.homedir()))
}

export class WebViews {
  private readonly entries = new Map<string, Entry>()
  private readonly hookedOwners = new WeakSet<WebContents>()
  private counter = 0
  private sessionReady = false

  /** `embed`: layer views over the sender's window (desktop mode); otherwise open real windows. */
  constructor(private readonly embed: boolean) {}

  register(): void {
    ipcMain.handle(IPC.webOpen, (event, url: string, options: WebOpenOptions = {}) => this.open(event.sender, url, options))
    ipcMain.handle(IPC.webOpenFile, (event, filePath: string, options: WebOpenOptions = {}) => this.openFile(event.sender, filePath, options))
    ipcMain.on(IPC.webSetBounds, (event, id: string, bounds: WebViewBounds, visible: boolean) => this.setBounds(event.sender, id, bounds, visible))
    ipcMain.handle(IPC.webClose, (event, id: string) => this.close(id, event.sender))
    ipcMain.handle(IPC.webOpenPreview, (event, target: string, options: WebOpenOptions = {}) => this.openPreview(event.sender, target, options))
    ipcMain.handle(IPC.webNavigate, (event, id: string, target: string) => this.navigate(event.sender, id, target))
    ipcMain.handle(IPC.webReload, (event, id: string) => {
      const contents = this.contentsFor(id, event.sender)
      contents?.reloadIgnoringCache()
    })
  }

  private readonly previewRoots = new Map<string, string | null>()

  /**
   * A Studio preview: a web page (usually the dev server on localhost) or a local file inside the
   * project folder (`options.root`), for static sites. Links between the project's own pages work.
   */
  openPreview(owner: WebContents, target: string, options: WebOpenOptions): string {
    const root = typeof options.root === 'string' && options.root ? resolveHomePath(options.root) : null

    if (root && !root.startsWith(os.homedir() + path.sep)) {
      throw new Error('a preview folder must be inside your home folder')
    }

    this.prepareSession()
    this.preparePreviewSession()
    this.hookOwner(owner)
    const id = `web-${++this.counter}`
    const host = BrowserWindow.fromWebContents(owner)
    const title = typeof options.title === 'string' ? options.title.slice(0, 200) : 'Preview'
    const entry: Entry = this.embed && host && !host.isDestroyed() ? this.createEmbedded(id, host, owner, PREVIEW_PREFERENCES) : this.createDetached(id, owner, title, PREVIEW_PREFERENCES)
    this.entries.set(id, entry)
    this.previewRoots.set(id, root)
    const contents = entry.kind === 'view' ? entry.view.webContents : entry.win.webContents
    this.guardPreview(id, contents)
    this.navigate(owner, id, target)
    log('web', `opened preview ${id} (${entry.kind}) ${target}`)

    return id
  }

  /** Point a preview somewhere else (a new dev-server port, another page of the site). */
  navigate(owner: WebContents, id: string, target: string): void {
    const contents = this.contentsFor(id, owner)

    if (!contents || !this.previewRoots.has(id)) {
      throw new Error('no such preview')
    }

    const root = this.previewRoots.get(id) ?? null
    const url = isHttp(target) ? target : target.startsWith('file://') ? target : pathToFileURL(resolveHomePath(target)).toString()

    if (!previewAllows(url, root)) {
      throw new Error('a preview shows web pages or files inside the project folder')
    }

    void contents.loadURL(url).catch(error => log('web', `${id}: load failed: ${error instanceof Error ? error.message : String(error)}`))
  }

  private guardPreview(id: string, contents: WebContents): void {
    const allowed = (url: string) => previewAllows(url, this.previewRoots.get(id) ?? null)
    contents.setWindowOpenHandler(({ url }) => {
      if (allowed(url)) {
        void contents.loadURL(url).catch(() => undefined)
      }

      return { action: 'deny' }
    })
    contents.on('will-navigate', (event, url) => {
      if (!allowed(url)) {
        event.preventDefault()
      }
    })
    contents.on('will-redirect', (event, url) => {
      if (!allowed(url)) {
        event.preventDefault()
      }
    })
    contents.on('will-attach-webview', event => event.preventDefault())
    contents.on('page-title-updated', (_event, title) => this.emitFor(id, { id, type: 'title', title }))
    const reportUrl = () => {
      if (!contents.isDestroyed()) {
        this.emitFor(id, { id, type: 'url', url: contents.getURL() })
      }
    }
    contents.on('did-navigate', reportUrl)
    contents.on('did-navigate-in-page', reportUrl)
    contents.on('did-start-loading', () => this.emitFor(id, { id, type: 'loading', loading: true }))
    contents.on('did-stop-loading', () => this.emitFor(id, { id, type: 'loading', loading: false }))
    contents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
      if (isMainFrame && code !== -3) {
        this.emitFor(id, { id, type: 'error', error: `${description} (${url})` })
      }
    })
  }

  private previewReady = false

  private preparePreviewSession(): void {
    if (this.previewReady) {
      return
    }

    this.previewReady = true
    const preview = session.fromPartition(PREVIEW_PARTITION)
    preview.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
    preview.setPermissionCheckHandler(() => false)
    preview.setDevicePermissionHandler(() => false)
    preview.on('will-download', event => event.preventDefault())
  }

  open(owner: WebContents, url: string, options: WebOpenOptions): string {
    if (typeof url !== 'string' || !isHttp(url)) {
      throw new Error('only http(s) URLs may be opened in a Hermes OS web window')
    }

    this.prepareSession()
    this.hookOwner(owner)
    const id = `web-${++this.counter}`
    const host = BrowserWindow.fromWebContents(owner)
    const title = typeof options.title === 'string' ? options.title.slice(0, 200) : undefined
    const entry: Entry = this.embed && host && !host.isDestroyed() ? this.createEmbedded(id, host, owner) : this.createDetached(id, owner, title)
    this.entries.set(id, entry)
    const contents = entry.kind === 'view' ? entry.view.webContents : entry.win.webContents
    this.guard(id, contents, new URL(url).origin)
    void contents.loadURL(url).catch(error => log('web', `${id}: load failed: ${error instanceof Error ? error.message : String(error)}`))
    log('web', `opened ${id} (${entry.kind}) ${url}`)

    return id
  }

  /** Show a local file (PDF, image, text, media) inside Hermes OS; the view can never navigate elsewhere. */
  openFile(owner: WebContents, filePath: string, options: WebOpenOptions): string {
    const resolved = typeof filePath === 'string' ? path.resolve(filePath.replace(/^~(?=\/|$)/, os.homedir())) : ''
    const stat = resolved ? fs.statSync(resolved, { throwIfNoEntry: false }) : undefined

    if (!stat?.isFile()) {
      throw new Error(`${filePath} is not a file`)
    }

    if (!isViewable(resolved)) {
      throw new Error(`Hermes OS cannot display ${path.extname(resolved) || 'this kind of'} files yet`)
    }

    this.hookOwner(owner)
    const id = `web-${++this.counter}`
    const host = BrowserWindow.fromWebContents(owner)
    const title = typeof options.title === 'string' ? options.title.slice(0, 200) : path.basename(resolved)
    const entry: Entry = this.embed && host && !host.isDestroyed() ? this.createEmbedded(id, host, owner, VIEWER_PREFERENCES) : this.createDetached(id, owner, title, VIEWER_PREFERENCES)
    this.entries.set(id, entry)
    const contents = entry.kind === 'view' ? entry.view.webContents : entry.win.webContents
    this.prepareViewerSession()
    const fileUrl = pathToFileURL(resolved).toString()
    contents.setWindowOpenHandler(() => ({ action: 'deny' }))
    // A viewer shows one file: links inside a PDF or page never navigate the view.
    contents.on('will-navigate', (event, url) => {
      if (url !== fileUrl) {
        event.preventDefault()
      }
    })
    contents.on('will-attach-webview', event => event.preventDefault())
    contents.on('did-start-loading', () => this.emitFor(id, { id, type: 'loading', loading: true }))
    contents.on('did-stop-loading', () => this.emitFor(id, { id, type: 'loading', loading: false }))
    void contents.loadFile(resolved).catch(error => log('web', `${id}: load failed: ${error instanceof Error ? error.message : String(error)}`))
    log('web', `opened ${id} (${entry.kind}) file ${resolved}`)

    return id
  }

  private emitFor(id: string, event: WebViewEvent): void {
    const entry = this.entries.get(id)

    if (entry) {
      this.emit(entry, event)
    }
  }

  private viewerReady = false

  /** The viewer partition grants nothing either. */
  private prepareViewerSession(): void {
    if (this.viewerReady) {
      return
    }

    this.viewerReady = true
    const viewer = session.fromPartition('persist:hermes-viewer')
    viewer.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
    viewer.setPermissionCheckHandler(() => false)
    viewer.setDevicePermissionHandler(() => false)
    viewer.on('will-download', event => event.preventDefault())
  }

  setBounds(sender: WebContents, id: string, bounds: WebViewBounds, visible: boolean): void {
    const entry = this.entries.get(id)

    if (!entry || entry.owner !== sender || entry.kind !== 'view' || entry.host.isDestroyed()) {
      return
    }

    // The renderer measures in CSS pixels; the view is placed in device-independent pixels.
    const zoom = entry.host.webContents.getZoomFactor() || 1
    const scale = (value: number) => Math.round(Number(value) * zoom)
    entry.view.setBounds({ x: scale(bounds.x), y: scale(bounds.y), width: Math.max(1, scale(bounds.width)), height: Math.max(1, scale(bounds.height)) })
    // Rounded corners follow the frame (macOS and Windows honour this; elsewhere it is a no-op).
    entry.view.setBorderRadius(Math.max(0, scale(bounds.radius ?? 0)))
    entry.view.setVisible(Boolean(visible))
  }

  close(id: string, sender?: WebContents): void {
    const entry = this.entries.get(id)

    if (!entry || (sender && entry.owner !== sender)) {
      return
    }

    this.entries.delete(id)
    this.previewRoots.delete(id)

    if (entry.kind === 'view') {
      if (!entry.host.isDestroyed()) {
        entry.host.contentView.removeChildView(entry.view)
      }

      if (!entry.view.webContents.isDestroyed()) {
        entry.view.webContents.close()
      }
    } else if (!entry.win.isDestroyed()) {
      entry.win.close()
    }

    this.emit(entry, { id, type: 'closed' })
    log('web', `closed ${id}`)
  }

  /** The guest contents of a view this owner opened (for typing/editing into a web page). */
  contentsFor(id: string, owner: WebContents): WebContents | null {
    const entry = this.entries.get(id)

    if (!entry || entry.owner !== owner) {
      return null
    }

    const contents = entry.kind === 'view' ? entry.view.webContents : entry.win.webContents

    return contents.isDestroyed() ? null : contents
  }

  closeAll(owner?: WebContents): void {
    for (const [id, entry] of [...this.entries]) {
      if (!owner || entry.owner === owner) {
        this.close(id)
      }
    }
  }

  private createEmbedded(id: string, host: BrowserWindow, owner: WebContents, preferences: Electron.WebPreferences = GUEST_PREFERENCES): EmbeddedView {
    const view = new WebContentsView({ webPreferences: { ...preferences } })
    // Hidden until the renderer reports the frame's content rect, so nothing flashes at (0, 0).
    view.setVisible(false)
    view.setBounds({ x: 0, y: 0, width: 1, height: 1 })
    view.setBackgroundColor('#ffffff')
    host.contentView.addChildView(view)
    view.webContents.on('destroyed', () => this.close(id))

    return { kind: 'view', id, view, host, owner }
  }

  private createDetached(id: string, owner: WebContents, title?: string, preferences: Electron.WebPreferences = GUEST_PREFERENCES): DetachedView {
    const win = new BrowserWindow({
      ...DETACHED_SIZE,
      frame: false,
      title: title ?? 'Hermes OS · Web',
      backgroundColor: '#ffffff',
      webPreferences: { ...preferences }
    })
    // The title is the window's identity for the compositor; the page title travels as an event.
    win.on('page-title-updated', event => event.preventDefault())
    win.on('closed', () => this.close(id))

    return { kind: 'window', id, win, owner }
  }

  /** Navigation policy and event mirroring for one guest. */
  private guard(id: string, contents: WebContents, origin: string): void {
    contents.setWindowOpenHandler(({ url }) => {
      // Same-origin popups become navigations of the same view; everything else is denied.
      if (isHttp(url) && new URL(url).origin === origin) {
        void contents.loadURL(url).catch(() => undefined)
      }

      return { action: 'deny' }
    })
    contents.on('will-navigate', (event, url) => {
      if (!isHttp(url)) {
        event.preventDefault()
      }
    })
    contents.on('will-redirect', (event, url) => {
      if (!isHttp(url)) {
        event.preventDefault()
      }
    })
    // No <webview>, no devtools shortcuts, no drag-and-drop file navigation in the guest.
    contents.on('will-attach-webview', event => event.preventDefault())
    contents.on('before-input-event', (event, input) => {
      if (input.type === 'keyDown' && (input.key === 'F12' || (input.key.toLowerCase() === 'i' && input.alt && (input.meta || input.control)))) {
        event.preventDefault()
      }
    })

    const entryFor = () => this.entries.get(id)
    contents.on('page-title-updated', (_event, title) => {
      const entry = entryFor()

      if (entry) {
        this.emit(entry, { id, type: 'title', title })
      }
    })
    const reportUrl = () => {
      const entry = entryFor()

      if (entry && !contents.isDestroyed()) {
        this.emit(entry, { id, type: 'url', url: contents.getURL() })
      }
    }
    contents.on('did-navigate', reportUrl)
    contents.on('did-navigate-in-page', reportUrl)
    contents.on('did-start-loading', () => {
      const entry = entryFor()

      if (entry) {
        this.emit(entry, { id, type: 'loading', loading: true })
      }
    })
    contents.on('did-stop-loading', () => {
      const entry = entryFor()

      if (entry) {
        this.emit(entry, { id, type: 'loading', loading: false })
      }
    })
  }

  private emit(entry: Entry, event: WebViewEvent): void {
    if (!entry.owner.isDestroyed()) {
      entry.owner.send(IPC.webEvent, event)
    }
  }

  /** A renderer that reloads or goes away takes its views with it. */
  private hookOwner(owner: WebContents): void {
    if (this.hookedOwners.has(owner)) {
      return
    }

    this.hookedOwners.add(owner)
    owner.on('did-navigate', () => this.closeAll(owner))
    owner.on('destroyed', () => this.closeAll(owner))
  }

  /** The guest partition grants nothing: no camera, mic, notifications, clipboard, or downloads. */
  private prepareSession(): void {
    if (this.sessionReady) {
      return
    }

    this.sessionReady = true
    const guest = session.fromPartition(PARTITION)
    guest.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
    guest.setPermissionCheckHandler(() => false)
    guest.setDevicePermissionHandler(() => false)
    guest.on('will-download', event => event.preventDefault())
  }
}

export function registerWebIpc(embed: boolean): WebViews {
  const views = new WebViews(embed)
  views.register()

  return views
}
