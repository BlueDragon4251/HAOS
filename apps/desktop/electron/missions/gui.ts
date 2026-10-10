/** Actual native mission windows. Chromium renderer isolation is the authority boundary. */
import { randomUUID } from 'node:crypto'
import { BrowserWindow, session } from 'electron'
import { guiId, missionDocument, validateGuiAction, type GuiRequest, type GuiPoll } from '../../shared/gui.ts'
import { managedMissions, nativeGuiRequest } from './client.ts'

export class MissionBrowser {
  private windows = new Map<string, { mission: string; win: BrowserWindow; documentSession: string }>()
  constructor(private visible = true) {}

  retain(mission: string | null): void {
    for (const [id, entry] of this.windows) {
      if (entry.mission !== mission) {
        if (!entry.win.isDestroyed()) entry.win.destroy()
        this.windows.delete(id)
      }
    }
  }

  async execute(request: GuiRequest): Promise<Record<string, unknown>> {
    if (!guiId(request.id) || !guiId(request.mission)) throw new Error('Invalid GUI scope')
    const action = validateGuiAction(request.action)
    if (action.operation === 'state') {
      return { windows: [...this.windows].filter(([, e]) => e.mission === request.mission && !e.win.isDestroyed()).map(([window]) => ({ window, width: 800, height: 600 })) }
    }
    if (action.operation === 'open') {
      if ([...this.windows.values()].some(e => e.mission === request.mission && !e.win.isDestroyed())) throw new Error('Mission already has a browser')
      const window = randomUUID()
      const isolated = session.fromPartition(`haos-mission-${window}`, { cache: false })
      isolated.setPermissionRequestHandler((_wc, _permission, reply) => reply(false))
      isolated.setPermissionCheckHandler(() => false)
      isolated.on('will-download', event => event.preventDefault())
      // Only the one broker-generated top document can load. No file/http/WS/extension
      // resources, even when caller HTML adds its own CSP or redirects an iframe.
      const url = `data:text/html;charset=utf-8,${encodeURIComponent(missionDocument(request.mission, action.html))}`
      isolated.webRequest.onBeforeRequest((details, reply) => reply({ cancel: details.url !== url || details.resourceType !== 'mainFrame' }))
      const win = new BrowserWindow({
        width: 800, height: 600, useContentSize: true, show: false, resizable: false, frame: false,
        minimizable: false, maximizable: false, fullscreenable: false, alwaysOnTop: false, focusable: false,
        title: `HAOS Mission ${request.mission}`, autoHideMenuBar: true,
        webPreferences: { session: isolated, sandbox: true, contextIsolation: true, nodeIntegration: false, javascript: false,
          nodeIntegrationInSubFrames: false, webviewTag: false, webSecurity: true, allowRunningInsecureContent: false,
          safeDialogs: true, navigateOnDragDrop: false, devTools: false, spellcheck: false }
      })
      win.setMenu(null)
      win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
      win.webContents.on('will-navigate', event => event.preventDefault())
      win.webContents.on('will-frame-navigate', event => event.preventDefault())
      win.webContents.on('will-attach-webview', event => event.preventDefault())
      win.webContents.on('page-title-updated', event => event.preventDefault())
      win.webContents.on('will-prevent-unload', event => event.preventDefault())
      win.webContents.on('render-process-gone', () => { if (!win.isDestroyed()) win.destroy() })
      win.on('unresponsive', () => { if (!win.isDestroyed()) win.destroy() })
      // Agent input goes directly to the scoped renderer. Seat input must not paste
      // owner clipboard contents into a mission or select files in a native dialog.
      win.setIgnoreMouseEvents(true)
      const entry = { mission: request.mission, win, documentSession: '' }
      this.windows.set(window, entry)
      win.on('closed', () => {
        this.windows.delete(window)
        void isolated.clearStorageData()
      })
      try {
        // No document scripts can run. Load first to create the renderer before
        // enabling CDP; then intercept choosers before any input/display action.
        await win.loadURL(url)
        win.webContents.debugger.attach('1.3')
        await win.webContents.debugger.sendCommand('Page.enable')
        // Browser file inputs cannot summon a host file chooser, including programmatic clicks.
        await win.webContents.debugger.sendCommand('Page.setInterceptFileChooserDialog', { enabled: true })
        const setup: Promise<void>[] = []
        const documents: string[] = []
        let setupFailed = false
        win.webContents.debugger.on('message', (_event, method, params) => {
          if (method !== 'Target.attachedToTarget') return
          const id = String(params.sessionId)
          setup.push((async () => {
            await win.webContents.debugger.sendCommand('Page.enable', {}, id)
            await win.webContents.debugger.sendCommand('Page.setInterceptFileChooserDialog', { enabled: true }, id)
            if (params.targetInfo.type === 'iframe' && params.targetInfo.url === 'about:srcdoc') documents.push(id)
            await win.webContents.debugger.sendCommand('Runtime.runIfWaitingForDebugger', {}, id)
          })().catch(() => {
            setupFailed = true
            if (!win.isDestroyed()) win.destroy()
          }))
        })
        await win.webContents.debugger.sendCommand('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: true, flatten: true })
        await Promise.all(setup)
        if (setupFailed || documents.length !== 1) throw new Error('Mission document target is ambiguous')
        entry.documentSession = documents[0]
        if (this.visible) win.showInactive()
        return { window, width: 800, height: 600 }
      } catch {
        if (!win.isDestroyed()) win.destroy()
        throw new Error('Mission browser failed to initialize')
      }
    }
    const entry = this.windows.get(action.window)
    if (!entry || entry.mission !== request.mission || entry.win.isDestroyed()) throw new Error('Window capability denied')
    const win = entry.win
    switch (action.operation) {
      case 'close': win.destroy(); break
      case 'focus': win.moveTop(); break
      case 'click':
        // Focus only this renderer; the native surface stays non-focusable to the seat.
        // CDP targets this renderer, never the seat/global pointer. No native window shortcuts.
        await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type: 'mousePressed', x: action.x, y: action.y - 48, button: 'left', clickCount: 1 }, entry.documentSession)
        await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type: 'mouseReleased', x: action.x, y: action.y - 48, button: 'left', clickCount: 1 }, entry.documentSession)
        // Native non-focusable surfaces must not depend on seat focus or a race
        // with cross-process hit-test updates. Focus only the actual input at the
        // requested point through this document's fixed DOM API, never caller JS.
        const point = await win.webContents.debugger.sendCommand('DOM.getNodeForLocation', { x: action.x, y: action.y - 48 }, entry.documentSession)
        const described = await win.webContents.debugger.sendCommand('DOM.describeNode', { backendNodeId: point.backendNodeId }, entry.documentSession)
        if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(described.node.nodeName)) {
          await win.webContents.debugger.sendCommand('DOM.focus', { backendNodeId: point.backendNodeId }, entry.documentSession)
        }
        break
      case 'type':
        await win.webContents.debugger.sendCommand('Input.insertText', { text: action.text }, entry.documentSession)
        await new Promise(resolve => setTimeout(resolve, 50))
        break
      case 'key': {
        const codes: Record<string, number> = { Tab: 9, Enter: 13, Backspace: 8, Delete: 46, ArrowUp: 38, ArrowDown: 40, ArrowLeft: 37, ArrowRight: 39, Home: 36, End: 35, Escape: 27 }
        const params = { key: action.key, windowsVirtualKeyCode: codes[action.key], nativeVirtualKeyCode: codes[action.key], modifiers: 0 }
        await win.webContents.debugger.sendCommand('Input.dispatchKeyEvent', { ...params, type: 'keyDown' }, entry.documentSession)
        await win.webContents.debugger.sendCommand('Input.dispatchKeyEvent', { ...params, type: 'keyUp' }, entry.documentSession)
        await new Promise(resolve => setTimeout(resolve, 20))
        break
      }
      case 'capture': {
        const shot = await win.webContents.capturePage({ x: 0, y: 0, width: 800, height: 600 })
        if (shot.isEmpty() || shot.getSize().width !== 800 || shot.getSize().height !== 600) throw new Error('Mission capture unavailable')
        const jpeg = shot.toJPEG(50)
        if (jpeg.length > 73728) throw new Error('Mission capture exceeds budget')
        return { window: action.window, width: 800, height: 600, jpeg: jpeg.toString('base64') }
      }
    }
    return { window: action.window }
  }
}

export class NativeGuiBroker {
  private stopped = true
  private browser = new MissionBrowser()
  private epoch = randomUUID()
  start(): void {
    if (!managedMissions() || !this.stopped) return
    this.stopped = false
    void this.run()
  }
  stop(): void { this.stopped = true; this.browser.retain(null) }
  private async run(): Promise<void> {
    let attached = false
    while (!this.stopped) {
      try {
        if (!attached) {
          await nativeGuiRequest('gui.attach', { epoch: this.epoch })
          attached = true
        }
        const poll = await nativeGuiRequest('gui.poll', { epoch: this.epoch }) as GuiPoll
        if (this.stopped) break
        this.browser.retain(poll.mission)
        if (poll.request) {
          let ok = true
          let result: Record<string, unknown>
          let timer: ReturnType<typeof setTimeout> | undefined
          try {
            result = await Promise.race([this.browser.execute(poll.request), new Promise<never>((_resolve, reject) => {
              timer = setTimeout(() => { this.browser.retain(null); reject(new Error('GUI deadline exceeded')) }, 5000)
            })])
          } catch { ok = false; result = {} }
          finally { if (timer) clearTimeout(timer) }
          // Lost acknowledgements are not retried as executions; the durable action
          // remains uncertain and the agent must inspect it using its original UUID.
          await nativeGuiRequest('gui.ack', { epoch: this.epoch, id: poll.request.id, ok, result })
        }
      } catch {
        this.browser.retain(null)
        attached = false
        this.epoch = randomUUID()
      }
      await new Promise(resolve => setTimeout(resolve, attached ? 200 : 1000))
    }
    this.browser.retain(null)
  }
}
