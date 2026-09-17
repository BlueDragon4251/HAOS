import { useStore } from '@nanostores/react'
import { IconX } from '@tabler/icons-react'
import { Dot } from '../../components/ui/primitives.tsx'
import { $toasts, dismissToast, type NotificationLevel } from '../../store/notifications.ts'
import { showSurface } from '../../store/surface.ts'

const TONE: Record<NotificationLevel, 'info' | 'ok' | 'warn' | 'danger'> = { info: 'info', success: 'ok', warn: 'warn', error: 'danger' }

export function Toasts() {
  const toasts = useStore($toasts)

  if (toasts.length === 0) {
    return null
  }

  return (
    <div className="pointer-events-none absolute top-11 right-3 z-(--z-overlay) flex w-80 flex-col gap-2">
      {toasts.map(toast => (
        <div key={toast.id} className="float pointer-events-auto flex items-start gap-2.5 rounded-md px-3 py-2.5 animate-rise">
          <Dot tone={TONE[toast.level]} className="mt-1.5" />
          <button type="button" className="min-w-0 flex-1 text-left" onClick={() => { if (toast.surface) { showSurface(toast.surface) } dismissToast(toast.id) }}>
            <div className="truncate text-[12.5px] font-medium text-fg">{toast.title}</div>
            {toast.body && <div className="mt-0.5 line-clamp-2 text-[12px] text-fg-2">{toast.body}</div>}
          </button>
          <button type="button" aria-label="Dismiss" onClick={() => dismissToast(toast.id)} className="-mr-1 flex size-6 shrink-0 items-center justify-center rounded-xs text-fg-3 hover:text-fg">
            <IconX size={13} />
          </button>
        </div>
      ))}
    </div>
  )
}
