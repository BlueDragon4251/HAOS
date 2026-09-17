import { atom } from 'nanostores'
import type { SurfaceId } from '../app/surfaces.ts'
import { $windowState } from './backend.ts'
import { onGatewayEvent } from './gateway.ts'

export type NotificationLevel = 'info' | 'success' | 'warn' | 'error'

export interface HermesNotification {
  id: string
  title: string
  body?: string
  level: NotificationLevel
  ts: number
  read: boolean
  surface?: SurfaceId
  /** Stable key for sticky notifications the backend clears explicitly. */
  key?: string
}

export const $notifications = atom<HermesNotification[]>([])
export const $notificationsOpen = atom(false)
/** Transient toasts: the most recent unread notifications, shown for a few seconds. */
export const $toasts = atom<HermesNotification[]>([])

const MAX = 200
let counter = 0

export interface NotifyInput {
  title: string
  body?: string
  level?: NotificationLevel
  surface?: SurfaceId
  key?: string
  /** Also raise a native notification when the window is unfocused. */
  native?: boolean
  toast?: boolean
}

export function notify(input: NotifyInput): HermesNotification {
  const existing = input.key ? $notifications.get().find(n => n.key === input.key) : undefined
  const item: HermesNotification = {
    id: existing?.id ?? `n${Date.now().toString(36)}${(counter++).toString(36)}`,
    title: input.title,
    body: input.body,
    level: input.level ?? 'info',
    ts: Date.now(),
    read: false,
    surface: input.surface,
    key: input.key
  }
  const rest = $notifications.get().filter(n => n.id !== item.id)
  $notifications.set([item, ...rest].slice(0, MAX))

  if (input.toast !== false) {
    $toasts.set([item, ...$toasts.get().filter(t => t.id !== item.id)].slice(0, 3))
    setTimeout(() => $toasts.set($toasts.get().filter(t => t.id !== item.id)), 6000)
  }

  if (input.native && !$windowState.get().focused) {
    void window.hermesOS.notifications.native(item.title, item.body ?? '')
  }

  return item
}

export function dismissToast(id: string): void {
  $toasts.set($toasts.get().filter(t => t.id !== id))
}

export function markAllRead(): void {
  $notifications.set($notifications.get().map(n => (n.read ? n : { ...n, read: true })))
}

export function clearNotifications(): void {
  $notifications.set([])
}

const levelFrom = (value: string | undefined): NotificationLevel =>
  value === 'error' ? 'error' : value === 'warn' || value === 'warning' ? 'warn' : value === 'success' ? 'success' : 'info'

export function bindNotificationEvents(): () => void {
  const offShow = onGatewayEvent('notification.show', event => {
    const payload = event.payload

    if (!payload?.text) {
      return
    }

    notify({ title: 'Hermes', body: payload.text, level: levelFrom(payload.level), key: payload.key ?? undefined, surface: 'chat' })
  })
  const offClear = onGatewayEvent('notification.clear', event => {
    const key = event.payload?.key

    if (key) {
      $notifications.set($notifications.get().filter(n => n.key !== key))
    }
  })
  const offCron = onGatewayEvent('cron.changed', () => {
    notify({ title: 'Tasks updated', body: 'A scheduled task changed', level: 'info', surface: 'tasks', key: 'cron.changed', toast: false })
  })

  return () => {
    offShow()
    offClear()
    offCron()
  }
}
