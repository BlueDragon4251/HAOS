/** Fixed capability for mission-owned local Chromium windows. No host/window/URL/eval API. */
export type GuiAction =
  | { operation: 'open'; html: string }
  | { operation: 'state' }
  | { operation: 'focus' | 'close' | 'capture' | 'inspect' | 'read'; window: string }
  | { operation: 'click'; window: string; x: number; y: number }
  | { operation: 'scroll'; window: string; x: number; y: number; deltaX: number; deltaY: number }
  | { operation: 'type'; window: string; text: string }
  | { operation: 'key'; window: string; key: string }

export interface GuiRequest { id: string; mission: string; action: GuiAction }
export interface GuiPoll { mission: string | null; request: GuiRequest | null }
export const GUI_WINDOW_LIMIT = 4
export const GUI_KEYS = new Set(['Tab', 'Enter', 'Backspace', 'Delete', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'])
export const guiId = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value)

export function validateGuiAction(value: unknown): GuiAction {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid GUI action')
  const data = value as Record<string, unknown>
  const fields = ['operation']
  const op = data.operation
  if (typeof op !== 'string') throw new Error('Invalid GUI operation')
  if (op === 'open') {
    fields.push('html')
    if (typeof data.html !== 'string' || new TextEncoder().encode(data.html).length > 32768 || !data.html.length) throw new Error('Invalid local document')
    if (/<\s*(?:iframe|frame|frameset|object|embed|applet)\b/i.test(data.html)) throw new Error('Nested application surfaces denied')
  } else if (op !== 'state') {
    if (!['focus', 'close', 'capture', 'inspect', 'read', 'click', 'scroll', 'type', 'key'].includes(String(op))) throw new Error('GUI capability denied')
    fields.push('window')
    if (!guiId(data.window)) throw new Error('Invalid window ID')
  }
  if (op === 'click' || op === 'scroll') {
    fields.push('x', 'y')
    if (!Number.isInteger(data.x) || !Number.isInteger(data.y) || Number(data.x) < 0 || Number(data.x) >= 800 || Number(data.y) < 48 || Number(data.y) >= 600) throw new Error('Click outside mission document')
  }
  if (op === 'scroll') {
    fields.push('deltaX', 'deltaY')
    if (!Number.isInteger(data.deltaX) || !Number.isInteger(data.deltaY) || Math.abs(Number(data.deltaX)) > 552 || Math.abs(Number(data.deltaY)) > 552 || (data.deltaX === 0 && data.deltaY === 0)) throw new Error('Invalid scoped scroll')
  }
  if (op === 'type') {
    fields.push('text')
    if (typeof data.text !== 'string' || !data.text.length || new TextEncoder().encode(data.text).length > 4096 || /[\x00-\x1f]/.test(data.text)) throw new Error('Invalid plain text')
  }
  if (op === 'key') {
    fields.push('key')
    if (!GUI_KEYS.has(String(data.key))) throw new Error('Shortcut capability denied')
  }
  if (Object.keys(data).length !== fields.length || fields.some(key => !(key in data))) throw new Error('Unexpected GUI parameters')
  return value as GuiAction
}

const escape = (text: string) => text.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!))

export function missionDocument(mission: string, html: string): string {
  if (!guiId(mission)) throw new Error('Invalid mission ID')
  return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-src about:; connect-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"><title>HAOS Mission ${mission}</title><style>html,body{margin:0;width:800px;height:600px;overflow:hidden;background:#122136;color:white;font:14px sans-serif}header{box-sizing:border-box;height:48px;padding:8px;overflow:hidden}iframe{border:0;width:800px;height:552px;background:white}</style></head><body><header>Hermes mission ${mission}<br>Isolated local browser · no owner authority</header><iframe sandbox srcdoc="${escape(html)}"></iframe></body></html>`
}
