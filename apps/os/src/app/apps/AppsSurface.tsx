import { IconApps } from '@tabler/icons-react'
import { memo, useEffect, useMemo, useState } from 'react'
import type { InstalledApp } from '../../../shared/ipc.ts'
import { EmptyState, Spinner } from '../../components/ui/primitives.tsx'
import { ErrorNote, SurfaceFrame } from '../../components/ui/surface-frame.tsx'
import { useLocalData } from '../../lib/use-async.ts'
import { notify } from '../../store/notifications.ts'

export function AppsSurface() {
  const [query, setQuery] = useState('')
  const apps = useLocalData(() => window.heraldOS.apps.list())
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()

    return (apps.data ?? []).filter(app => !needle || app.name.toLowerCase().includes(needle))
  }, [apps.data, query])

  const launch = async (app: InstalledApp) => {
    try {
      await window.heraldOS.apps.launch(app.path)
      notify({ title: `Opened ${app.name}`, level: 'info', toast: false })
    } catch (error) {
      notify({ title: `Could not open ${app.name}`, body: error instanceof Error ? error.message : String(error), level: 'error' })
    }
  }

  return (
    <SurfaceFrame
      title="Apps"
      subtitle={apps.data ? `${apps.data.length} installed` : undefined}
      actions={<input autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Search apps" className="h-7 w-56 rounded-sm bg-surface px-2.5 text-[12.5px] outline-none hairline placeholder:text-fg-4 focus:shadow-[0_0_0_1px_var(--color-accent)]" />}
    >
      {apps.error && <ErrorNote message={apps.error} onRetry={apps.reload} />}
      {apps.loading && !apps.data && (
        <div className="flex h-32 items-center justify-center">
          <Spinner />
        </div>
      )}
      {!apps.loading && filtered.length === 0 && <EmptyState icon={<IconApps />} title="No apps match" />}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-2">
        {filtered.map(app => (
          <AppTile key={app.path} app={app} onLaunch={() => void launch(app)} />
        ))}
      </div>
    </SurfaceFrame>
  )
}

const AppTile = memo(function AppTile({ app, onLaunch }: { app: InstalledApp; onLaunch: () => void }) {
  const [icon, setIcon] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void window.heraldOS.apps
      .icon(app.path)
      .then(url => {
        if (!cancelled) {
          setIcon(url)
        }
      })
      .catch(() => undefined)

    return () => {
      cancelled = true
    }
  }, [app.path])

  return (
    <button type="button" onDoubleClick={onLaunch} onKeyDown={event => event.key === 'Enter' && onLaunch()} className="group flex flex-col items-center gap-2 rounded-lg px-2 py-3 hover:bg-white/4 focus:bg-white/6">
      <div className="flex size-14 items-center justify-center transition-transform duration-100 group-active:scale-95">
        {icon ? <img src={icon} alt="" className="size-14" draggable={false} /> : <div className="size-12 rounded-xl bg-surface-2" />}
      </div>
      <span className="w-full truncate text-center text-[12px] text-fg-2 group-hover:text-fg">{app.name}</span>
    </button>
  )
})
