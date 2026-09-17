import {
  IconApps,
  IconBell,
  IconBolt,
  IconCalendarClock,
  IconChartBar,
  IconFolder,
  IconHome,
  IconMessage,
  IconSettings,
  IconTerminal2,
  IconUsers
} from '@tabler/icons-react'
import type { ComponentType } from 'react'

export type SurfaceId = 'home' | 'chat' | 'agents' | 'tasks' | 'skills' | 'files' | 'apps' | 'terminal' | 'system' | 'settings'

export interface SurfaceDef {
  id: SurfaceId
  label: string
  icon: ComponentType<{ size?: number; className?: string; stroke?: number }>
  /** Digit shortcut with Cmd. */
  shortcut?: string
}

/** Table-driven: the rail, the command bar and keyboard shortcuts all read this list. */
export const SURFACES: readonly SurfaceDef[] = [
  { id: 'home', label: 'Home', icon: IconHome, shortcut: '1' },
  { id: 'chat', label: 'Hermes', icon: IconMessage, shortcut: '2' },
  { id: 'agents', label: 'Agents', icon: IconUsers, shortcut: '3' },
  { id: 'tasks', label: 'Tasks', icon: IconCalendarClock, shortcut: '4' },
  { id: 'skills', label: 'Skills', icon: IconBolt, shortcut: '5' },
  { id: 'files', label: 'Files', icon: IconFolder, shortcut: '6' },
  { id: 'apps', label: 'Apps', icon: IconApps, shortcut: '7' },
  { id: 'terminal', label: 'Terminal', icon: IconTerminal2, shortcut: '8' },
  { id: 'system', label: 'System', icon: IconChartBar, shortcut: '9' },
  { id: 'settings', label: 'Settings', icon: IconSettings, shortcut: ',' }
]

export const NOTIFICATIONS_ICON = IconBell

export const surfaceById = (id: SurfaceId): SurfaceDef => SURFACES.find(s => s.id === id) ?? SURFACES[0]
