import { IconArrowUp, IconChevronRight, IconEye, IconEyeOff, IconFile, IconFolder, IconFolderOpen, IconMessage, IconRefresh } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import type { DirEntry, FilePreview } from '../../../shared/ipc.ts'
import { Button } from '../../components/ui/button.tsx'
import { EmptyState, Spinner } from '../../components/ui/primitives.tsx'
import { ErrorNote } from '../../components/ui/surface-frame.tsx'
import { cn } from '../../lib/cn.ts'
import { formatBytes, formatRelative } from '../../lib/format.ts'
import { useLocalData } from '../../lib/use-async.ts'
import { sendPrompt } from '../../store/chat.ts'
import { showSurface } from '../../store/surface.ts'

const QUICK = ['Desktop', 'Documents', 'Downloads', 'Pictures', 'Apps', 'Projects', 'Developer']

export function FilesSurface() {
  const [home, setHome] = useState<string | null>(null)
  const [cwd, setCwd] = useState<string | null>(null)
  const [selected, setSelected] = useState<DirEntry | null>(null)
  const [showHidden, setShowHidden] = useState(false)
  const [preview, setPreview] = useState<FilePreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  useEffect(() => {
    void window.heraldOS.fs.home().then(dir => {
      setHome(dir)
      setCwd(current => current ?? dir)
    })
  }, [])

  const listing = useLocalData(() => (cwd ? window.heraldOS.fs.readDir(cwd) : Promise.resolve([] as DirEntry[])), [cwd])
  const entries = useMemo(() => (listing.data ?? []).filter(entry => showHidden || !entry.hidden), [listing.data, showHidden])
  const quickLinks = useMemo(() => (home ? QUICK.map(name => ({ name, path: `${home}/${name}` })) : []), [home])

  useEffect(() => {
    setPreview(null)
    setPreviewError(null)

    if (!selected || selected.kind === 'directory') {
      return
    }

    let cancelled = false
    window.heraldOS.fs
      .readFile(selected.path)
      .then(result => {
        if (!cancelled) {
          setPreview(result)
        }
      })
      .catch(error => {
        if (!cancelled) {
          setPreviewError(error instanceof Error ? error.message : String(error))
        }
      })

    return () => {
      cancelled = true
    }
  }, [selected])

  const navigate = (dir: string) => {
    setCwd(dir)
    setSelected(null)
  }
  const parent = cwd && cwd !== '/' ? cwd.replace(/\/[^/]+\/?$/, '') || '/' : null
  const crumbs = useMemo(() => {
    if (!cwd) {
      return []
    }

    const parts = cwd.split('/').filter(Boolean)

    return parts.map((part, index) => ({ label: part, path: '/' + parts.slice(0, index + 1).join('/') }))
  }, [cwd])

  const askHermes = (entry: DirEntry) => {
    showSurface('chat')
    void sendPrompt(`Take a look at ${entry.path} and tell me what it is.`)
  }

  return (
    <div className="flex h-full">
      <aside className="flex w-52 shrink-0 flex-col gap-0.5 border-r border-hairline px-2 py-3">
        <div className="mb-1 px-2 text-[11px] tracking-[0.08em] text-fg-3 uppercase">Places</div>
        {home && <PlaceButton active={cwd === home} label="Home" onClick={() => navigate(home)} />}
        {quickLinks.map(link => (
          <PlaceButton key={link.path} active={cwd === link.path} label={link.name} onClick={() => navigate(link.path)} />
        ))}
        <PlaceButton active={cwd === '/'} label="Macintosh HD" onClick={() => navigate('/')} />
        <PlaceButton active={cwd === '/Applications'} label="Applications" onClick={() => navigate('/Applications')} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center gap-1 px-4">
          <Button variant="ghost" size="icon-sm" aria-label="Up" disabled={!parent} onClick={() => parent && navigate(parent)}>
            <IconArrowUp size={15} />
          </Button>
          <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden text-[12.5px]">
            <button type="button" onClick={() => navigate('/')} className="shrink-0 rounded-xs px-1 text-fg-3 hover:text-fg">/</button>
            {crumbs.map((crumb, index) => (
              <span key={crumb.path} className="flex min-w-0 items-center">
                {index > 0 && <IconChevronRight size={12} className="shrink-0 text-fg-4" />}
                <button type="button" onClick={() => navigate(crumb.path)} className={cn('truncate rounded-xs px-1 hover:text-fg', index === crumbs.length - 1 ? 'text-fg' : 'text-fg-3')}>
                  {crumb.label}
                </button>
              </span>
            ))}
          </div>
          <Button variant="ghost" size="icon-sm" aria-label={showHidden ? 'Hide hidden files' : 'Show hidden files'} onClick={() => setShowHidden(v => !v)}>
            {showHidden ? <IconEyeOff size={15} /> : <IconEye size={15} />}
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Refresh" onClick={listing.reload}>
            <IconRefresh size={15} />
          </Button>
          {cwd && (
            <Button variant="ghost" size="sm" onClick={() => void window.heraldOS.fs.reveal(cwd)}>
              Finder
            </Button>
          )}
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="min-w-0 flex-1 overflow-y-auto px-3 pb-3">
            {listing.error && <ErrorNote message={listing.error} onRetry={listing.reload} />}
            {listing.loading && !listing.data && (
              <div className="flex h-24 items-center justify-center">
                <Spinner />
              </div>
            )}
            {entries.map(entry => (
              <button
                key={entry.path}
                type="button"
                onClick={() => setSelected(entry)}
                onDoubleClick={() => (entry.kind === 'directory' ? navigate(entry.path) : void window.heraldOS.fs.openPath(entry.path))}
                className={cn('flex w-full items-center gap-3 rounded-md px-2.5 py-1.5 text-left text-[12.5px]', selected?.path === entry.path ? 'bg-white/6 text-fg' : 'text-fg-2 hover:bg-white/4')}
              >
                <span className={cn('shrink-0', entry.kind === 'directory' ? 'text-accent' : 'text-fg-4')}>{entry.kind === 'directory' ? <IconFolder size={15} /> : <IconFile size={15} />}</span>
                <span className={cn('min-w-0 flex-1 truncate', entry.hidden && 'opacity-60')}>{entry.name}</span>
                <span className="w-20 shrink-0 text-right text-[11.5px] tabular-nums text-fg-4">{entry.kind === 'directory' ? '' : formatBytes(entry.size)}</span>
                <span className="w-20 shrink-0 text-right text-[11.5px] text-fg-4">{formatRelative(entry.modifiedAt)}</span>
              </button>
            ))}
            {!listing.loading && entries.length === 0 && !listing.error && <EmptyState icon={<IconFolderOpen />} title="Empty folder" />}
          </div>

          {selected && (
            <aside className="flex w-[380px] shrink-0 flex-col border-l border-hairline">
              <div className="flex flex-col gap-1 px-4 py-3">
                <div className="selectable truncate text-[13px]">{selected.name}</div>
                <div className="selectable truncate font-mono text-[11px] text-fg-4">{selected.path}</div>
                <div className="text-[11.5px] text-fg-3">
                  {selected.kind === 'directory' ? 'Folder' : formatBytes(selected.size)} · modified {formatRelative(selected.modifiedAt)}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Button size="sm" onClick={() => void window.heraldOS.fs.openPath(selected.path)}>Open</Button>
                  <Button size="sm" variant="ghost" onClick={() => void window.heraldOS.fs.reveal(selected.path)}>Reveal</Button>
                  <Button size="sm" variant="ghost" onClick={() => void window.heraldOS.fs.openIn('vscode', selected.path)}>VS Code</Button>
                  <Button size="sm" variant="ghost" onClick={() => askHermes(selected)}>
                    <IconMessage size={13} /> Ask Hermes
                  </Button>
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
                {previewError && <ErrorNote message={previewError} />}
                {preview?.kind === 'text' && (
                  <pre className="selectable rounded-md bg-surface p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-fg-2 hairline">
                    {preview.content}
                    {preview.truncated && '\n… (truncated)'}
                  </pre>
                )}
                {preview?.kind === 'image' && <img src={preview.content} alt={selected.name} className="max-w-full rounded-md hairline" />}
                {preview?.kind === 'binary' && <div className="text-[12px] text-fg-3">Binary file. Open it in its app or ask Hermes about it.</div>}
                {preview?.kind === 'too-large' && <div className="text-[12px] text-fg-3">Too large to preview here.</div>}
              </div>
            </aside>
          )}
        </div>
      </div>
    </div>
  )
}

function PlaceButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={cn('flex h-7 items-center gap-2 rounded-md px-2 text-left text-[12.5px]', active ? 'bg-white/6 text-fg' : 'text-fg-2 hover:bg-white/4')}>
      <IconFolder size={14} className={active ? 'text-accent' : 'text-fg-4'} />
      <span className="truncate">{label}</span>
    </button>
  )
}
