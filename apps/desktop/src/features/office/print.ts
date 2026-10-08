/* Print views: self-contained HTML pages main prints to PDF with scripts off. */

export const escapeHtml = (text: string): string => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

export function printPage(title: string, css: string, body: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>${css}</style></head><body>${body}</body></html>`
}

/** Text from a file's bytes: UTF-8, or Windows-1252 for an older file that is not UTF-8 (which saving changes). */
export function decodeText(bytes: Uint8Array): { text: string; notes: string[] } {
  try {
    return { text: new TextDecoder('utf-8', { fatal: true }).decode(bytes), notes: [] }
  } catch {
    return { text: new TextDecoder('windows-1252').decode(bytes), notes: ['The file is not in UTF-8; Herald reads it as Windows-1252 and saves it as UTF-8.'] }
  }
}

export const encodeText = (text: string): Uint8Array => new TextEncoder().encode(text)

/** An id for a new Univer unit. */
export const unitId = (prefix: string): string => `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`
