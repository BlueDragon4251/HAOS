import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useState } from 'react'
import type { InstalledApp } from '../../../shared/ipc.ts'
import { AppGlyph, HermesAvatar } from '../../components/app-icon.tsx'
import { cn } from '../../lib/cn.ts'
import { notify } from '../../store/notifications.ts'
import { $applicationsOpen } from '../../store/surface.ts'
import { $windows, focusWindow, MAIN_WINDOW_ID, showPage } from '../../store/windows.ts'
import { useNativeApps } from '../../store/native-apps.ts'

interface DockItem {
  id: string
  label: string
  render: () => React.ReactNode
  onClick: () => void
  running?: boolean
}

const PINNED_NATIVE: { label: string; names: string[] }[] = [
  { label: 'Files', names: ['Finder'] },
  { label: 'Safari', names: ['Safari', 'Google Chrome', 'Arc'] },
  { label: 'Mail', names: ['Mail'] },
  { label: 'Calendar', names: ['Calendar'] },
  { label: 'Notes', names: ['Notes'] }
]

export function Dock() {
  const windows = useStore($windows)
  const { apps, iconFor } = useNativeApps()
  const [bouncing, setBouncing] = useState<string | null>(null)

  const main = windows[MAIN_WINDOW_ID]
  const openHermes = () => {
    if (main && main.phase !== 'minimized') {
      focusWindow(MAIN_WINDOW_ID)
    } else {
      showPage('overview')
    }
  }

  const launch = async (app: InstalledApp) => {
    setBouncing(app.path)
    setTimeout(() => setBouncing(null), 450)

    try {
      await window.hermesOS.apps.launch(app.path)
    } catch (error) {
      notify({ title: `Could not open ${app.name}`, body: error instanceof Error ? error.message : String(error), level: 'error' })
    }
  }

  const items = useMemo<DockItem[]>(() => {
    const list: DockItem[] = [
      {
        id: 'hermes',
        label: 'Hermes',
        render: () => <HermesAvatar size={44} rounded={11} />,
        onClick: openHermes,
        running: Boolean(main) && main.phase !== 'minimized'
      }
    ]

    for (const pin of PINNED_NATIVE) {
      if (pin.label === 'Files') {
        list.push({ id: 'files', label: 'Files', render: () => <NativeIcon src={iconFor(apps.find(a => a.name === 'Finder')?.path)} fallback="files" />, onClick: () => showPage('files') })

        continue
      }

      const app = pin.names.map(n => apps.find(a => a.name === n)).find(Boolean)

      if (app) {
        list.push({ id: app.path, label: app.name, render: () => <NativeIcon src={iconFor(app.path)} fallback="grid" />, onClick: () => void launch(app) })
      }
    }

    list.push({ id: 'applications', label: 'Applications', render: () => <span className="icon-tile size-11 rounded-[11px]"><AppGlyph id="grid" size={22} /></span>, onClick: () => $applicationsOpen.set(true) })
    list.push({ id: 'trash', label: 'Trash', render: () => <span className="flex size-11 items-center justify-center rounded-[11px] bg-white/6 text-fg-2"><AppGlyph id="trash" size={22} /></span>, onClick: () => void window.hermesOS.fs.openPath('~/.Trash') })

    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apps, iconFor, main?.phase])

  return (
    <nav className="pointer-events-none absolute inset-x-0 bottom-0 z-(--z-dock) flex h-(--dock-h) items-end justify-center pb-3" aria-label="Dock">
      <div className="glass pointer-events-auto flex items-end gap-2 rounded-2xl px-3 py-2">
        {items.map(item => (
          <button
            key={item.id}
            type="button"
            aria-label={item.label}
            title={item.label}
            onClick={item.onClick}
            className={cn('group relative flex flex-col items-center transition-transform duration-150 ease-out hover:-translate-y-1.5 hover:scale-[1.1] active:scale-95', bouncing === item.id && 'dock-bounce')}
          >
            {item.render()}
            <span className={cn('mt-1 size-1 rounded-full transition-opacity', item.running ? 'bg-fg opacity-90' : 'opacity-0')} />
          </button>
        ))}
      </div>
    </nav>
  )
}

function NativeIcon({ src, fallback }: { src?: string; fallback: 'files' | 'grid' }) {
  const [failed, setFailed] = useState(false)

  useEffect(() => setFailed(false), [src])

  if (!src || failed) {
    return (
      <span className="icon-tile size-11 rounded-[11px]">
        <AppGlyph id={fallback} size={22} />
      </span>
    )
  }

  return <img src={src} alt="" width={44} height={44} draggable={false} onError={() => setFailed(true)} className="size-11 drop-shadow-[0_4px_10px_rgba(0,10,60,.5)]" />
}
