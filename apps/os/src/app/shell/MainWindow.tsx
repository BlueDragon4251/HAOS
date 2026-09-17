import { useStore } from '@nanostores/react'
import { type ComponentType, Suspense, lazy } from 'react'
import { $page } from '../../store/windows.ts'
import type { PageId } from '../apps.ts'
import { Sidebar } from './Sidebar.tsx'

// Pages load on first visit and stay mounted afterwards (keep-alive: chat, files, terminals).
const PAGE_VIEW: Record<PageId, ComponentType> = {
  overview: lazy(() => import('../overview/OverviewPage.tsx').then(m => ({ default: m.OverviewPage }))),
  hermes: lazy(() => import('../hermes/HermesPage.tsx').then(m => ({ default: m.HermesPage }))),
  missions: lazy(() => import('../missions/MissionsPage.tsx').then(m => ({ default: m.MissionsPage }))),
  memory: lazy(() => import('../memory/MemoryPage.tsx').then(m => ({ default: m.MemoryPage }))),
  files: lazy(() => import('../files/FilesPage.tsx').then(m => ({ default: m.FilesPage }))),
  automations: lazy(() => import('../automations/AutomationsPage.tsx').then(m => ({ default: m.AutomationsPage }))),
  connections: lazy(() => import('../connections/ConnectionsPage.tsx').then(m => ({ default: m.ConnectionsPage }))),
  settings: lazy(() => import('../settings/SettingsPage.tsx').then(m => ({ default: m.SettingsPage })))
}

const visited = new Set<PageId>(['overview'])

/** Sidebar + the current page. Visited pages stay mounted; only the active one is visible. */
export function MainWindow() {
  const page = useStore($page)
  visited.add(page)

  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="relative min-w-0 flex-1 py-3 pr-3">
        <div className="glass-card relative h-full overflow-hidden rounded-xl" style={{ background: 'rgba(5, 18, 66, 0.42)' }}>
          {[...visited].map(id => {
            const View = PAGE_VIEW[id]
            const active = id === page

            return (
              <div key={id} className={active ? 'page-enter absolute inset-0' : 'absolute inset-0'} style={active ? undefined : { visibility: 'hidden', pointerEvents: 'none' }} aria-hidden={!active}>
                <Suspense fallback={<PageSkeleton />}>
                  <View />
                </Suspense>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <div className="shimmer h-10 w-64 rounded-lg" />
      <div className="shimmer h-9 w-full rounded-lg" />
      <div className="grid flex-1 grid-cols-3 gap-3">
        <div className="shimmer rounded-xl" />
        <div className="shimmer rounded-xl" />
        <div className="shimmer rounded-xl" />
      </div>
    </div>
  )
}
