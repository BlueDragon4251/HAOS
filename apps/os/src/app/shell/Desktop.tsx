import { useStore } from '@nanostores/react'
import { lazy, Suspense } from 'react'
import { Spinner } from '../../components/ui/primitives.tsx'
import { $commandBarOpen, $surface } from '../../store/surface.ts'
import { AgentsSurface } from '../agents/AgentsSurface.tsx'
import { AppsSurface } from '../apps/AppsSurface.tsx'
import { ChatSurface } from '../chat/ChatSurface.tsx'
import { FilesSurface } from '../files/FilesSurface.tsx'
import { HomeSurface } from '../home/HomeSurface.tsx'
import { SettingsSurface } from '../settings/SettingsSurface.tsx'
import { SkillsSurface } from '../skills/SkillsSurface.tsx'
import type { SurfaceId } from '../surfaces.ts'
import { SystemSurface } from '../system/SystemSurface.tsx'
import { TasksSurface } from '../tasks/TasksSurface.tsx'
import { CommandBar } from './CommandBar.tsx'
import { NotificationsPanel } from './NotificationsPanel.tsx'
import { Rail } from './Rail.tsx'
import { RequestHost } from './RequestHost.tsx'
import { StatusBar } from './StatusBar.tsx'
import { Toasts } from './Toasts.tsx'

// xterm is heavy; load the terminal only when the user first opens it. It then stays mounted.
const TerminalSurface = lazy(() => import('../terminal/TerminalSurface.tsx').then(m => ({ default: m.TerminalSurface })))

const SURFACE_VIEW: Record<SurfaceId, () => React.JSX.Element> = {
  home: HomeSurface,
  chat: ChatSurface,
  agents: AgentsSurface,
  tasks: TasksSurface,
  skills: SkillsSurface,
  files: FilesSurface,
  apps: AppsSurface,
  terminal: () => (
    <Suspense fallback={<div className="flex h-full items-center justify-center"><Spinner /></div>}>
      <TerminalSurface />
    </Suspense>
  ),
  system: SystemSurface,
  settings: SettingsSurface
}

/** Expensive, stateful surfaces stay mounted once visited. Visibility is not lifecycle. */
const KEEP_ALIVE = new Set<SurfaceId>(['chat', 'terminal', 'files'])

export function Desktop({ surface }: { surface: SurfaceId }) {
  const commandBarOpen = useStore($commandBarOpen)
  const visited = useVisited(surface)

  return (
    <div className="flex h-full w-full flex-col">
      <StatusBar />
      <div className="flex min-h-0 flex-1">
        <Rail />
        <main className="relative min-w-0 flex-1 overflow-hidden">
          {[...visited].map(id => {
            const View = SURFACE_VIEW[id]
            const active = id === surface

            if (!active && !KEEP_ALIVE.has(id)) {
              return null
            }

            return (
              <div key={id} className="absolute inset-0" style={active ? undefined : { visibility: 'hidden', pointerEvents: 'none' }} aria-hidden={!active}>
                <View />
              </div>
            )
          })}
        </main>
      </div>
      <RequestHost />
      <Toasts />
      <NotificationsPanel />
      {commandBarOpen && <CommandBar />}
    </div>
  )
}

const visitedSet = new Set<SurfaceId>(['home'])

function useVisited(current: SurfaceId): Set<SurfaceId> {
  visitedSet.add(current)
  // Subscribe so a surface change re-renders; the set itself is module-level by design.
  useStore($surface)

  return visitedSet
}
