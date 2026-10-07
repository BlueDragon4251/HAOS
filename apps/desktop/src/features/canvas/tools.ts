/*
 * The tool in hand and its options, shared by the tool palette, the viewport and the shortcuts.
 */

import { atom } from 'nanostores'

export type ToolId = 'move' | 'hand' | 'zoom'

export interface ToolDef {
  id: ToolId
  label: string
  /** The key that picks it. */
  key: string
}

export const TOOLS: readonly ToolDef[] = [
  { id: 'move', label: 'Move', key: 'v' },
  { id: 'hand', label: 'Hand', key: 'h' },
  { id: 'zoom', label: 'Zoom', key: 'z' }
]

export const $tool = atom<ToolId>('move')

/** Move tool: pick the layer under the pointer instead of moving the active one. */
export const $autoSelect = atom(false)

/** Space held: the Hand tool for as long as it is down. */
export const $spaceHeld = atom(false)
