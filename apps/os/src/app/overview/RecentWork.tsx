import { IconFolder } from '@tabler/icons-react'
import { GlassCard, LinkAction, MoreButton, Section } from '../../components/ui/glass.tsx'
import { formatRelative } from '../../lib/format.ts'
import { useLocalData } from '../../lib/use-async.ts'
import { showPage } from '../../store/windows.ts'
import { FileThumb, IconTile, Shimmer } from './shared.tsx'

const SHOWN = 4

/** The last few files touched on this Mac, as thumbnail cards that open in their default app. */
export function RecentWork() {
  const recent = useLocalData(() => window.hermesOS.fs.recent(8), [])
  const files = (recent.data ?? []).slice(0, SHOWN)

  return (
    <Section title="Recent work" action={<LinkAction onClick={() => showPage('files')}>See all</LinkAction>}>
      {recent.loading && !recent.data ? (
        <div className="grid grid-cols-2 gap-3">
          {Array.from({ length: SHOWN }, (_, i) => (
            <Shimmer key={i} className="h-[76px] rounded-xl" />
          ))}
        </div>
      ) : files.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line px-4 py-5 text-center text-[12.5px] text-fg-3">{recent.error ? 'Recent files are unavailable right now.' : 'Nothing recent yet. Files you work on will show up here.'}</div>
      ) : (
        <div className="stagger grid grid-cols-2 gap-3">
          {files.map(file => {
            const open = () => void window.hermesOS.fs.openPath(file.path)
            const kind = file.kind === 'directory' ? 'Folder' : file.extension ? file.extension.replace(/^\./, '').toUpperCase() : 'File'
            const edited = formatRelative(file.modifiedAt)

            return (
              <GlassCard key={file.path} interactive onClick={open} className="flex items-center gap-3 p-2.5">
                {file.kind === 'directory' ? (
                  <IconTile size={56} className="rounded-lg">
                    <IconFolder />
                  </IconTile>
                ) : (
                  <FileThumb path={file.path} size={256} className="h-[56px] w-[84px] shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium text-fg" title={file.path}>
                    {file.name}
                  </div>
                  <div className="truncate text-[11.5px] text-fg-3">
                    {kind}
                    {edited ? ` · Edited ${edited}` : ''}
                  </div>
                </div>
                <MoreButton
                  aria-label={`Open ${file.name}`}
                  onClick={event => {
                    event.stopPropagation()
                    open()
                  }}
                />
              </GlassCard>
            )
          })}
        </div>
      )}
    </Section>
  )
}
