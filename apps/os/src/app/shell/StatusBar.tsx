import { useStore } from '@nanostores/react'
import { IconArrowsMaximize, IconArrowsMinimize, IconBell, IconSearch } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { BrandMark } from '../../components/brand-mark.tsx'
import { Dot, Kbd } from '../../components/ui/primitives.tsx'
import { cn } from '../../lib/cn.ts'
import { formatClock, formatPercent } from '../../lib/format.ts'
import { $backend, $windowState } from '../../store/backend.ts'
import { $activeChat } from '../../store/chat.ts'
import { $connection } from '../../store/gateway.ts'
import { $notifications, $notificationsOpen } from '../../store/notifications.ts'
import { toggleCommandBar } from '../../store/surface.ts'
import { $systemStats, useSystemStats } from '../../store/system.ts'

function useClock(): Date {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 15_000)

    return () => clearInterval(timer)
  }, [])

  return now
}

export function StatusBar() {
  const backend = useStore($backend)
  const connection = useStore($connection)
  const chat = useStore($activeChat)
  const notifications = useStore($notifications)
  const open = useStore($notificationsOpen)
  const win = useStore($windowState)
  const stats = useStore($systemStats)
  const now = useClock()
  useSystemStats()

  const unread = notifications.filter(n => !n.read).length
  const online = backend.phase === 'ready' && connection === 'open'
  const tone = online ? 'ok' : backend.phase === 'failed' ? 'danger' : 'warn'
  const label = online ? 'Hermes online' : backend.phase === 'ready' ? 'Connecting' : backend.phase === 'failed' ? 'Hermes offline' : 'Starting Hermes'
  const model = chat?.info.model

  return (
    <header className="drag-region flex h-9 shrink-0 items-center justify-between px-3 text-[12px] text-fg-2 select-none">
      <div className="flex items-center gap-3 pl-[70px]">
        <div className="flex items-center gap-2">
          <BrandMark size={15} />
          <span className="font-medium text-fg">Hermes OS</span>
        </div>
        <span className="text-fg-4">/</span>
        <div className="flex items-center gap-1.5">
          <Dot tone={tone} pulse={!online} />
          <span>{label}</span>
        </div>
        {model && (
          <>
            <span className="text-fg-4">/</span>
            <span className="text-fg-3">{model}</span>
          </>
        )}
      </div>

      <button type="button" onClick={() => toggleCommandBar(true)} className="no-drag flex h-6 items-center gap-2 rounded-sm px-2 text-fg-3 hover:bg-white/5 hover:text-fg-2">
        <IconSearch size={13} />
        <span>Ask Hermes or search</span>
        <Kbd>⌘K</Kbd>
      </button>

      <div className="no-drag flex items-center gap-1">
        {stats && (
          <div className="mr-2 flex items-center gap-3 tabular-nums text-fg-3">
            <span title="CPU">CPU {formatPercent(stats.cpuPercent)}</span>
            <span title="Memory">MEM {formatPercent((stats.memoryUsed / stats.memoryTotal) * 100)}</span>
            {stats.battery.present && <span title="Battery">{stats.battery.charging ? '⚡' : ''}{stats.battery.percent}%</span>}
          </div>
        )}
        <button
          type="button"
          aria-label="Notifications"
          onClick={() => $notificationsOpen.set(!open)}
          className={cn('relative flex size-7 items-center justify-center rounded-sm hover:bg-white/5', open && 'bg-white/5 text-fg')}
        >
          <IconBell size={15} />
          {unread > 0 && <span className="absolute top-1 right-1 size-1.5 rounded-full bg-accent" />}
        </button>
        <button type="button" aria-label="Toggle fullscreen" onClick={() => void window.hermesOS.window.toggleFullscreen()} className="flex size-7 items-center justify-center rounded-sm hover:bg-white/5">
          {win.fullscreen ? <IconArrowsMinimize size={14} /> : <IconArrowsMaximize size={14} />}
        </button>
        <span className="ml-1 whitespace-nowrap text-right tabular-nums text-fg">{formatClock(now)}</span>
      </div>
    </header>
  )
}
