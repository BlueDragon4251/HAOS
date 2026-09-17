import { useStore } from '@nanostores/react'
import { IconBattery, IconBattery1, IconBattery2, IconBattery3, IconBattery4, IconBatteryCharging, IconBell, IconCheck, IconChevronDown, IconSearch, IconWifi, IconWifiOff } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { HermesAvatar } from '../../components/app-icon.tsx'
import { cn } from '../../lib/cn.ts'
import { $backend } from '../../store/backend.ts'
import { $connection } from '../../store/gateway.ts'
import { $notifications, $notificationsOpen } from '../../store/notifications.ts'
import { $activeSpace, $spaces, setActiveSpace } from '../../store/spaces.ts'
import { toggleCommandBar } from '../../store/surface.ts'
import { $systemStats, useNetworkStatus, useSystemStats } from '../../store/system.ts'
import { $focusedTitle } from '../../store/windows.ts'

function useClock(): Date {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 10_000)

    return () => clearInterval(timer)
  }, [])

  return now
}

const fmtTime = (d: Date) => d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
const fmtDate = (d: Date) => d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

export function MenuBar() {
  const title = useStore($focusedTitle)
  const space = useStore($activeSpace)
  const spaces = useStore($spaces)
  const backend = useStore($backend)
  const connection = useStore($connection)
  const notifications = useStore($notifications)
  const notificationsOpen = useStore($notificationsOpen)
  const stats = useStore($systemStats)
  const network = useNetworkStatus()
  const now = useClock()
  const [spaceMenu, setSpaceMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  useSystemStats()

  useEffect(() => {
    if (!spaceMenu) {
      return
    }

    const onDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setSpaceMenu(false)
      }
    }
    window.addEventListener('mousedown', onDown)

    return () => window.removeEventListener('mousedown', onDown)
  }, [spaceMenu])

  const unread = notifications.filter(n => !n.read).length
  const online = backend.phase === 'ready' && connection === 'open'
  const battery = stats?.battery

  return (
    <header className="drag-region absolute inset-x-0 top-0 z-(--z-menubar) flex h-(--menubar-h) items-center justify-between px-3 text-[12.5px] text-fg select-none" style={{ background: 'linear-gradient(180deg, rgba(3,10,40,.55), rgba(3,10,40,.15))' }}>
      <div className="flex items-center gap-2.5 pl-[74px]">
        <HermesAvatar size={18} rounded={5} />
        <span className="font-semibold">Hermes OS</span>
        {title !== 'Hermes OS' && (
          <>
            <span className="text-fg-4">·</span>
            <span className="text-fg-2">{title}</span>
          </>
        )}
        {!online && <span className="ml-2 rounded-full bg-warn/20 px-2 py-0.5 text-[11px] text-warn">{backend.phase === 'failed' ? 'Hermes offline' : 'Starting Hermes'}</span>}
      </div>

      <div ref={menuRef} className="no-drag relative">
        <button
          type="button"
          onClick={() => setSpaceMenu(v => !v)}
          className="flex h-6 items-center gap-1.5 rounded-full border border-line-strong bg-accent/35 px-3 text-[12px] font-medium text-fg shadow-[0_2px_10px_rgba(47,125,255,.35)] hover:bg-accent/50"
        >
          <span className="size-1.5 rounded-full" style={{ background: space.color }} />
          {space.name}
          <IconChevronDown size={13} className="text-fg-2" />
        </button>
        {spaceMenu && (
          <div className="float absolute top-8 left-1/2 w-48 -translate-x-1/2 overflow-hidden rounded-xl p-1 animate-pop">
            {spaces.map(s => (
              <button
                key={s.id}
                type="button"
                onClick={() => {
                  setActiveSpace(s.id)
                  setSpaceMenu(false)
                }}
                className={cn('flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-[12.5px] hover:bg-white/8', s.id === space.id ? 'text-fg' : 'text-fg-2')}
              >
                <span className="size-2 rounded-full" style={{ background: s.color }} />
                <span className="flex-1 text-left">{s.name}</span>
                {s.id === space.id && <IconCheck size={14} className="text-accent-strong" />}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="no-drag flex items-center gap-3.5">
        <button type="button" aria-label="Search" onClick={() => toggleCommandBar(true)} className="flex size-6 items-center justify-center rounded-md hover:bg-white/10">
          <IconSearch size={15} />
        </button>
        <span title={network?.wifi?.connected ? `Wi-Fi ${network.wifi.ssid ?? ''}`.trim() : network?.online ? 'Wired' : 'Offline'}>
          {network?.online === false ? <IconWifiOff size={15} className="text-fg-3" /> : <IconWifi size={15} />}
        </span>
        {battery?.present && (
          <span className="flex items-center gap-1.5 tabular-nums">
            {battery.charging ? <IconBatteryCharging size={17} /> : (battery.percent ?? 0) > 80 ? <IconBattery4 size={17} /> : (battery.percent ?? 0) > 55 ? <IconBattery3 size={17} /> : (battery.percent ?? 0) > 30 ? <IconBattery2 size={17} /> : (battery.percent ?? 0) > 10 ? <IconBattery1 size={17} /> : <IconBattery size={17} />}
            <span className="text-[12px]">{battery.percent}%</span>
          </span>
        )}
        <button type="button" aria-label="Notifications" onClick={() => $notificationsOpen.set(!notificationsOpen)} className={cn('relative flex size-6 items-center justify-center rounded-md hover:bg-white/10', notificationsOpen && 'bg-white/10')}>
          <IconBell size={15} />
          {unread > 0 && <span className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-accent-strong" />}
        </button>
        <span className="tabular-nums">{fmtDate(now)}</span>
        <span className="tabular-nums font-medium">{fmtTime(now)}</span>
      </div>
    </header>
  )
}
