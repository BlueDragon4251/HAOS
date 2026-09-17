import { useStore } from '@nanostores/react'
import { cn } from '../../lib/cn.ts'
import { $agents } from '../../store/agents.ts'
import { $pendingRequests } from '../../store/requests.ts'
import { $surface, showSurface } from '../../store/surface.ts'
import { SURFACES, type SurfaceId } from '../surfaces.ts'

export function Rail() {
  const active = useStore($surface)
  const pending = useStore($pendingRequests)
  const agents = useStore($agents)
  const runningAgents = Object.values(agents).filter(a => a.status === 'running' || a.status === 'queued').length
  const badges: Partial<Record<SurfaceId, number>> = { chat: pending.length, agents: runningAgents }

  return (
    <nav className="flex w-14 shrink-0 flex-col items-center gap-1 py-2" aria-label="Surfaces">
      {SURFACES.map(surface => {
        const Icon = surface.icon
        const isActive = surface.id === active
        const badge = badges[surface.id]

        return (
          <button
            key={surface.id}
            type="button"
            onClick={() => showSurface(surface.id)}
            aria-label={surface.label}
            aria-current={isActive ? 'page' : undefined}
            title={`${surface.label}  ⌘${surface.shortcut ?? ''}`}
            className={cn(
              'group relative flex size-10 items-center justify-center rounded-md transition-colors duration-100',
              isActive ? 'bg-white/8 text-fg' : 'text-fg-3 hover:bg-white/5 hover:text-fg-2',
              surface.id === 'settings' && 'mt-auto'
            )}
          >
            <Icon size={19} stroke={1.6} />
            {isActive && <span className="absolute left-0 h-4 w-0.5 rounded-r bg-accent" />}
            {badge ? <span className="absolute top-1.5 right-1.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-accent px-1 text-[9px] font-semibold text-accent-fg">{badge}</span> : null}
          </button>
        )
      })}
    </nav>
  )
}
