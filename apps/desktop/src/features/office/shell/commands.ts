import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { matches } from '../../../lib/shortcuts.ts'
import type { OfficeSession } from '../session.ts'

/*
 * The menus every Office app shares (File and Edit) and the app's own, in one table with their
 * shortcuts. The file shortcuts work while typing in a document, as they do in other office apps.
 */

export interface OfficeCommand {
  id: string
  label: string
  /** `mod` is ⌘ on the Mac and Ctrl elsewhere. */
  keys?: string
  run: () => void
  enabled?: () => boolean
  checked?: () => boolean
  dividerBefore?: boolean
  submenu?: OfficeCommand[]
}

export interface OfficeMenu {
  id: string
  label: string
  items: OfficeCommand[]
}

/** What the shared menus need from the app: its session, and its own commands by menu. */
export interface MenuSource<Model> {
  session: OfficeSession<Model>
  /** Commands added to File (after Export), Edit (after Redo), and menus of the app's own. */
  file?: OfficeCommand[]
  edit?: OfficeCommand[]
  menus?: OfficeMenu[]
  /** Whether the app saves any format here (Slides saves nothing until .pptx). */
  canSave: boolean
}

export function officeMenus<Model>(source: MenuSource<Model>): OfficeMenu[] {
  const { session } = source
  const doc = () => session.active()
  const hasDoc = () => Boolean(doc())

  return [
    {
      id: 'file',
      label: 'File',
      items: [
        { id: 'new', label: 'New', keys: 'mod+n', run: () => session.create() },
        { id: 'open', label: 'Open…', keys: 'mod+o', run: () => void session.openPicked() },
        { id: 'save', label: 'Save', keys: 'mod+s', enabled: () => hasDoc() && source.canSave, run: () => void session.save().catch(() => {}), dividerBefore: true },
        { id: 'save-as', label: 'Save As…', keys: 'mod+shift+s', enabled: () => hasDoc() && source.canSave, run: () => void session.save(doc(), { as: true }).catch(() => {}) },
        { id: 'export-pdf', label: 'Export as PDF…', keys: 'mod+p', enabled: hasDoc, run: () => void session.exportPdf() },
        ...(source.file ?? []),
        {
          id: 'notes',
          label: 'What Herald changed…',
          enabled: () => Boolean(doc()?.notes.length),
          run: () => {
            const active = doc()

            if (active) {
              session.$dialog.set({ kind: 'notes', title: `Opening ${active.name}`, notes: active.notes })
            }
          },
          dividerBefore: true
        },
        { id: 'close', label: 'Close', keys: 'mod+w', enabled: hasDoc, run: () => session.$dialog.set({ kind: 'close', key: doc()!.key }), dividerBefore: true }
      ]
    },
    {
      id: 'edit',
      label: 'Edit',
      items: [{ id: 'undo', label: 'Undo', enabled: hasDoc, run: () => doc()?.editor?.undo() }, { id: 'redo', label: 'Redo', enabled: hasDoc, run: () => doc()?.editor?.redo() }, ...(source.edit ?? [])]
    },
    ...(source.menus ?? [])
  ]
}

const everyCommand = (commands: readonly OfficeCommand[]): OfficeCommand[] => commands.flatMap((command) => [command, ...everyCommand(command.submenu ?? [])])

/** Run the command a key press is for; true when one ran. */
export function runShortcut(event: KeyboardEvent | ReactKeyboardEvent, menus: readonly OfficeMenu[]): boolean {
  for (const menu of menus) {
    for (const command of everyCommand(menu.items)) {
      if (command.keys && matches(event, command.keys) && (command.enabled?.() ?? true)) {
        command.run()

        return true
      }
    }
  }

  return false
}
