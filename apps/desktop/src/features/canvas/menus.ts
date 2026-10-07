/*
 * Herald Canvas's menus and their shortcuts, in one table so the two never disagree. Shortcuts
 * follow the usual photo-editor keys (⌘J duplicates, ⌘E merges down, ⌘G groups).
 */

import { atom } from 'nanostores'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import {
  addFolder,
  addLayer,
  addMask,
  arrange,
  deleteMask,
  deletePicked,
  duplicatePicked,
  flattenImage,
  groupPicked,
  mergeDown,
  mergeTarget,
  toggleClipping,
  toggleMask,
  ungroupActive
} from './actions.ts'
import type { CanvasDocument } from './engine/document.ts'
import { $autosave, exportDocument, notify, openPath, save, setAutosave } from './store.ts'
import { actualPixels, fitToScreen, zoomStep } from './view-state.ts'

export const isMac = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform)

/** Dialogs the window shows on request. */
export type CanvasDialog = { kind: 'new' } | { kind: 'close'; key: string } | null

export const $dialog = atom<CanvasDialog>(null)

export interface CanvasCommand {
  id: string
  label: string | ((doc: CanvasDocument | null) => string)
  /** `mod` is ⌘ on the Mac and Ctrl elsewhere: `mod+shift+z`. */
  keys?: string
  run: (doc: CanvasDocument | null) => void
  /** Off when it cannot apply; commands that need a document are off without one. */
  enabled?: (doc: CanvasDocument) => boolean
  needsDocument?: boolean
  checked?: () => boolean
  dividerBefore?: boolean
}

export interface CanvasMenu {
  id: string
  label: string
  items: CanvasCommand[]
}

const onDoc = (run: (doc: CanvasDocument) => void) => (doc: CanvasDocument | null) => doc && run(doc)

const openFile = async (): Promise<void> => {
  const file = await window.heraldOS.canvas.pickOpen()

  if (file) {
    openPath(file).catch((error: unknown) => notify(`Could not open ${file.split('/').pop()}: ${error instanceof Error ? error.message : String(error)}`, 'error'))
  }
}

export const MENUS: CanvasMenu[] = [
  {
    id: 'file',
    label: 'File',
    items: [
      { id: 'new', label: 'New…', keys: 'mod+n', run: () => $dialog.set({ kind: 'new' }) },
      { id: 'open', label: 'Open…', keys: 'mod+o', run: () => void openFile() },
      { id: 'save', label: 'Save', keys: 'mod+s', needsDocument: true, run: onDoc((doc) => void save(doc).catch(() => {})), dividerBefore: true },
      { id: 'save-as', label: 'Save As…', keys: 'mod+shift+s', needsDocument: true, run: onDoc((doc) => void save(doc, { as: true }).catch(() => {})) },
      { id: 'autosave', label: 'Save Automatically', checked: () => $autosave.get(), run: () => setAutosave(!$autosave.get()) },
      { id: 'export-png', label: 'Export as PNG…', keys: 'mod+alt+shift+w', needsDocument: true, run: onDoc((doc) => void exportDocument(doc, 'png')), dividerBefore: true },
      { id: 'export-jpeg', label: 'Export as JPEG…', needsDocument: true, run: onDoc((doc) => void exportDocument(doc, 'jpeg')) },
      { id: 'export-webp', label: 'Export as WebP…', needsDocument: true, run: onDoc((doc) => void exportDocument(doc, 'webp')) },
      { id: 'close', label: 'Close', keys: 'mod+w', needsDocument: true, run: onDoc((doc) => $dialog.set({ kind: 'close', key: doc.key })), dividerBefore: true }
    ]
  },
  {
    id: 'edit',
    label: 'Edit',
    items: [
      { id: 'undo', label: (doc) => (doc?.history.undoLabel ? `Undo ${doc.history.undoLabel}` : 'Undo'), keys: 'mod+z', needsDocument: true, enabled: (doc) => doc.history.canUndo, run: onDoc((doc) => doc.undo()) },
      { id: 'redo', label: (doc) => (doc?.history.redoLabel ? `Redo ${doc.history.redoLabel}` : 'Redo'), keys: 'mod+shift+z', needsDocument: true, enabled: (doc) => doc.history.canRedo, run: onDoc((doc) => doc.redo()) }
    ]
  },
  {
    id: 'image',
    label: 'Image',
    items: [{ id: 'flatten', label: 'Flatten Image', needsDocument: true, enabled: (doc) => doc.state.layers.length > 0, run: onDoc(flattenImage) }]
  },
  {
    id: 'layer',
    label: 'Layer',
    items: [
      { id: 'new-layer', label: 'New Layer', keys: 'mod+shift+n', needsDocument: true, run: onDoc(addLayer) },
      { id: 'new-folder', label: 'New Folder', needsDocument: true, run: onDoc(addFolder) },
      { id: 'duplicate', label: 'Duplicate', keys: 'mod+j', needsDocument: true, enabled: (doc) => doc.picked.length > 0, run: onDoc(duplicatePicked) },
      { id: 'delete', label: 'Delete', needsDocument: true, enabled: (doc) => doc.picked.length > 0, run: onDoc(deletePicked) },
      { id: 'group', label: 'Group Layers', keys: 'mod+g', needsDocument: true, enabled: (doc) => doc.picked.length > 0, run: onDoc(groupPicked), dividerBefore: true },
      { id: 'ungroup', label: 'Ungroup', keys: 'mod+shift+g', needsDocument: true, enabled: (doc) => Boolean(doc.active?.isGroup), run: onDoc(ungroupActive) },
      { id: 'mask', label: 'Add Mask', needsDocument: true, enabled: (doc) => Boolean(doc.active && !doc.active.mask), run: onDoc((doc) => addMask(doc)), dividerBefore: true },
      { id: 'mask-hide', label: 'Add Mask Hiding All', needsDocument: true, enabled: (doc) => Boolean(doc.active && !doc.active.mask), run: onDoc((doc) => addMask(doc, true)) },
      {
        id: 'mask-toggle',
        label: (doc) => (doc?.active?.maskEnabled === false ? 'Turn Mask On' : 'Turn Mask Off'),
        needsDocument: true,
        enabled: (doc) => Boolean(doc.active?.mask),
        run: onDoc(toggleMask)
      },
      { id: 'mask-delete', label: 'Delete Mask', needsDocument: true, enabled: (doc) => Boolean(doc.active?.mask), run: onDoc(deleteMask) },
      {
        id: 'clip',
        label: (doc) => (doc?.active?.maskSourceID ? 'Release Clipping Mask' : 'Create Clipping Mask'),
        keys: 'mod+alt+g',
        needsDocument: true,
        enabled: (doc) => Boolean(doc.active && !doc.active.isGroup),
        run: onDoc(toggleClipping),
        dividerBefore: true
      },
      { id: 'forward', label: 'Bring Forward', keys: 'mod+]', needsDocument: true, run: onDoc((doc) => arrange(doc, 'up')), dividerBefore: true },
      { id: 'backward', label: 'Send Backward', keys: 'mod+[', needsDocument: true, run: onDoc((doc) => arrange(doc, 'down')) },
      { id: 'front', label: 'Bring to Front', keys: 'mod+shift+]', needsDocument: true, run: onDoc((doc) => arrange(doc, 'top')) },
      { id: 'back', label: 'Send to Back', keys: 'mod+shift+[', needsDocument: true, run: onDoc((doc) => arrange(doc, 'bottom')) },
      { id: 'merge-down', label: 'Merge Down', keys: 'mod+e', needsDocument: true, enabled: (doc) => Boolean(mergeTarget(doc)), run: onDoc(mergeDown), dividerBefore: true }
    ]
  },
  {
    id: 'view',
    label: 'View',
    items: [
      { id: 'zoom-in', label: 'Zoom In', keys: 'mod+=', needsDocument: true, run: onDoc((doc) => zoomStep(doc, 1)) },
      { id: 'zoom-out', label: 'Zoom Out', keys: 'mod+-', needsDocument: true, run: onDoc((doc) => zoomStep(doc, -1)) },
      { id: 'fit', label: 'Fit on Screen', keys: 'mod+0', needsDocument: true, run: onDoc((doc) => fitToScreen(doc)) },
      { id: 'actual', label: 'Actual Pixels', keys: 'mod+1', needsDocument: true, run: onDoc(actualPixels) }
    ]
  }
]

export const commandLabel = (command: CanvasCommand, doc: CanvasDocument | null): string => (typeof command.label === 'function' ? command.label(doc) : command.label)

export const isEnabled = (command: CanvasCommand, doc: CanvasDocument | null): boolean => (command.needsDocument ? Boolean(doc) && (command.enabled?.(doc!) ?? true) : true)

/** How a shortcut reads on this system: ⇧⌘S on the Mac, Ctrl+Shift+S elsewhere. */
export function keysLabel(keys: string): string {
  const parts = keys.split('+')
  const key = parts.pop()!
  const named: Record<string, string> = { '=': '+', '-': '−' }
  const shown = named[key] ?? key.toUpperCase()

  if (isMac) {
    const symbols: Record<string, string> = { mod: '⌘', shift: '⇧', alt: '⌥', ctrl: '⌃' }
    const order = ['ctrl', 'alt', 'shift', 'mod']

    return `${order.filter((mod) => parts.includes(mod)).map((mod) => symbols[mod]).join('')}${shown}`
  }

  const words: Record<string, string> = { mod: 'Ctrl', shift: 'Shift', alt: 'Alt', ctrl: 'Ctrl' }

  return [...parts.map((mod) => words[mod]), shown].join('+')
}

/** Does a key press match a shortcut? */
export function matches(event: KeyboardEvent | ReactKeyboardEvent, keys: string): boolean {
  const parts = keys.split('+')
  const key = parts.pop()!
  const mod = isMac ? event.metaKey : event.ctrlKey

  if (parts.includes('mod') !== mod || parts.includes('shift') !== event.shiftKey || parts.includes('alt') !== event.altKey) {
    return false
  }

  if (isMac && event.ctrlKey && !parts.includes('ctrl')) {
    return false
  }

  // Shifted and option layers change event.key, so letters and digits match on the physical key.
  const code = event.code
  const pressed = /^Key[A-Z]$/.test(code) ? code.slice(3).toLowerCase() : /^Digit\d$/.test(code) ? code.slice(5) : event.key.toLowerCase()
  const aliases: Record<string, string[]> = { '=': ['=', '+'], '-': ['-', '_'], ']': [']', '}'], '[': ['[', '{'] }

  return (aliases[key] ?? [key]).includes(pressed) || (key === '=' && code === 'Equal') || (key === '-' && code === 'Minus') || (key === ']' && code === 'BracketRight') || (key === '[' && code === 'BracketLeft')
}

/** Run the command a key press is for; true when one ran. */
export function runShortcut(event: KeyboardEvent | ReactKeyboardEvent, doc: CanvasDocument | null): boolean {
  for (const menu of MENUS) {
    for (const command of menu.items) {
      if (command.keys && matches(event, command.keys) && isEnabled(command, doc)) {
        command.run(doc)

        return true
      }
    }
  }

  return false
}
