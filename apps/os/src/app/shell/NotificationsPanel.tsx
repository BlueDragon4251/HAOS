import { useStore } from '@nanostores/react'
import { IconBellOff } from '@tabler/icons-react'
import { useEffect } from 'react'
import { Button } from '../../components/ui/button.tsx'
import { Dot, EmptyState } from '../../components/ui/primitives.tsx'
import { formatRelative } from '../../lib/format.ts'
import { $notifications, $notificationsOpen, clearNotifications, markAllRead, type NotificationLevel } from '../../store/notifications.ts'
import { showSurface } from '../../store/surface.ts'

const TONE: Record<NotificationLevel, 'info' | 'ok' | 'warn' | 'danger'> = { info: 'info', success: 'ok', warn: 'warn', error: 'danger' }

export function NotificationsPanel() {
  const open = useStore($notificationsOpen)
  const items = useStore($notifications)

  useEffect(() => {
    if (!open) {
      return
    }

    markAllRead()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        $notificationsOpen.set(false)
      }
    }
    window.addEventListener('keydown', onKey)

    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  if (!open) {
    return null
  }

  return (
    <>
      <button type="button" aria-label="Close notifications" className="absolute inset-0 z-(--z-panel)" onClick={() => $notificationsOpen.set(false)} />
      <aside className="float absolute top-10 right-3 z-(--z-overlay) flex h-[min(70vh,640px)] w-[360px] flex-col rounded-lg animate-rise">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="text-[13px] font-medium">Notifications</div>
          <Button variant="ghost" size="sm" onClick={clearNotifications} disabled={items.length === 0}>
            Clear all
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {items.length === 0 ? (
            <EmptyState icon={<IconBellOff />} title="You're all caught up" description="Tool results, approvals and task updates appear here." />
          ) : (
            items.map(item => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  if (item.surface) {
                    showSurface(item.surface)
                    $notificationsOpen.set(false)
                  }
                }}
                className="flex w-full items-start gap-2.5 rounded-md px-2 py-2 text-left hover:bg-white/5"
              >
                <Dot tone={TONE[item.level]} className="mt-1.5" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[12.5px] text-fg">{item.title}</span>
                    <span className="shrink-0 text-[11px] text-fg-4">{formatRelative(item.ts)}</span>
                  </div>
                  {item.body && <div className="mt-0.5 line-clamp-3 text-[12px] text-fg-3">{item.body}</div>}
                </div>
              </button>
            ))
          )}
        </div>
      </aside>
    </>
  )
}
