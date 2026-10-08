import { useEffect, useRef } from 'react'
import { OFFICE_APP_NAMES, OFFICE_APPS, type OfficeApp } from '../../../shared/office/files.ts'
import { AppTile } from '../../components/app-icon.tsx'
import { cn } from '../../lib/cn.ts'
import { appById } from '../../shell/apps.ts'

/**
 * The Dock's Herald Office entry opens this: Docs, Sheets and Slides in one tile instead of three,
 * each showing whether it is open. It closes on a choice, a click elsewhere or Escape.
 */
export function OfficeChooser({ x, running, onChoose, onClose }: { x: number; running: ReadonlySet<OfficeApp>; onChoose: (app: OfficeApp) => void; onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      const target = event.target as Element | null

      // The Dock entry toggles the chooser itself.
      if (!panel.current?.contains(target) && !target?.closest?.('[data-dock-item="office"]')) {
        onClose()
      }
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)

    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  return (
    <div
      ref={panel}
      role="menu"
      aria-label="Herald Office"
      className="float menu-surface pointer-events-auto absolute bottom-[calc(var(--dock-h)+4px)] z-(--z-overlay) w-64 -translate-x-1/2 rounded-xl p-1.5 animate-pop"
      style={{ left: Math.min(Math.max(x, 140), window.innerWidth - 140) }}
    >
      {OFFICE_APPS.map((app) => (
        <button key={app} type="button" role="menuitem" onClick={() => onChoose(app)} className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-white/8">
          <AppTile id={appById(app).icon} size={30} />
          <span className="min-w-0 flex-1">
            <span className="block text-[12.5px] text-fg">{OFFICE_APP_NAMES[app]}</span>
            <span className="block truncate text-[11px] text-fg-3">{appById(app).tagline}</span>
          </span>
          <span className={cn('size-1.5 shrink-0 rounded-full', running.has(app) ? 'bg-fg opacity-90' : 'opacity-0')} aria-label={running.has(app) ? 'Open' : undefined} />
        </button>
      ))}
    </div>
  )
}
