import { type OfficeAbilities, type OfficeApp, officeAppFor } from '../../../shared/office/files.ts'
import { isPanels } from '../../store/shell.ts'
import { openApp } from '../../store/windows.ts'

let abilities: Promise<OfficeAbilities> | null = null
let known: OfficeAbilities = { libreOffice: false }

/** What the machine adds to the formats (LibreOffice for OpenDocument files), asked once. */
export function officeAbilities(): Promise<OfficeAbilities> {
  abilities ??= window.heraldOS.office
    .abilities()
    .catch(() => known)
    .then((found) => (known = found))

  return abilities
}

/** The Office app that edits `file` here, as far as is known now (menus are built at once). */
export function officeAppForFile(file: string): OfficeApp | null {
  void officeAbilities()

  return officeAppFor(file, known)
}

/** What opening needs of an app's session, whatever its documents hold. */
interface OpensFiles {
  open: (file: string) => Promise<unknown>
  create: () => unknown
  notify: (message: string, tone?: 'info' | 'error') => void
}

/** Show an Office app, opening a file in it (or a new document) when asked; its editor loads only when needed. */
export function openInOffice(app: OfficeApp, request: { file?: string; blank?: boolean } = {}): void {
  if (isPanels) {
    // Each app runs in its own window process there: the request goes over as the window's payload.
    const payload = request.file ? { path: request.file, at: Date.now() } : request.blank ? { command: 'new', at: Date.now() } : undefined
    openApp(app, { payload })

    return
  }

  openApp(app)

  if (!request.file && !request.blank) {
    return
  }

  const stores: Record<OfficeApp, () => Promise<OpensFiles>> = {
    docs: () => import('./docs/store.ts').then((m) => m.docsSession),
    sheets: () => import('./sheets/store.ts').then((m) => m.sheetsSession),
    slides: () => import('./slides/store.ts').then((m) => m.slidesSession)
  }
  void stores[app]().then((session) => {
    if (request.file) {
      const file = request.file
      session.open(file).catch((error: unknown) => session.notify(`Could not open ${file.split('/').pop()}: ${error instanceof Error ? error.message : String(error)}`, 'error'))
    } else {
      session.create()
    }
  })
}

export const openInDocs = (file?: string): void => openInOffice('docs', { file })
export const openInSheets = (file?: string): void => openInOffice('sheets', { file })
export const openInSlides = (file?: string): void => openInOffice('slides', { file })
