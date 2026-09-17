import { IconCalendarClock, IconPlayerPause, IconPlayerPlay, IconRefresh, IconRocket, IconTrash } from '@tabler/icons-react'
import { useEffect } from 'react'
import { Button } from '../../components/ui/button.tsx'
import { Badge, EmptyState } from '../../components/ui/primitives.tsx'
import { ErrorNote, SurfaceFrame } from '../../components/ui/surface-frame.tsx'
import { formatRelative } from '../../lib/format.ts'
import { type CronJob, rest } from '../../lib/rest.ts'
import { useBackendData } from '../../lib/use-async.ts'
import { sendPrompt } from '../../store/chat.ts'
import { onGatewayEvent } from '../../store/gateway.ts'
import { notify } from '../../store/notifications.ts'
import { showSurface } from '../../store/surface.ts'

const toMs = (value: string | number | null | undefined): number | undefined => {
  if (value == null) {
    return undefined
  }

  if (typeof value === 'number') {
    return value < 1e12 ? value * 1000 : value
  }

  const parsed = Date.parse(value)

  return Number.isNaN(parsed) ? undefined : parsed
}

export function TasksSurface() {
  const jobs = useBackendData(() => rest.get<CronJob[]>('/api/cron/jobs'))

  useEffect(() => onGatewayEvent('cron.changed', () => jobs.reload()), [jobs.reload])

  const act = async (job: CronJob, action: 'pause' | 'resume' | 'trigger' | 'delete') => {
    try {
      if (action === 'delete') {
        await rest.del(`/api/cron/jobs/${encodeURIComponent(job.id)}`, job.profile ? { profile: job.profile } : undefined)
      } else {
        await rest.post(`/api/cron/jobs/${encodeURIComponent(job.id)}/${action}`, undefined, job.profile ? { profile: job.profile } : undefined)
      }

      notify({ title: job.name || 'Task', body: action === 'trigger' ? 'Run started' : `${action}d`, level: 'success', surface: 'tasks' })
      jobs.reload()
    } catch (error) {
      notify({ title: 'Task action failed', body: error instanceof Error ? error.message : String(error), level: 'error', surface: 'tasks' })
    }
  }

  const rows = [...(jobs.data ?? [])].sort((a, b) => (toMs(a.next_run_at) ?? Infinity) - (toMs(b.next_run_at) ?? Infinity))

  return (
    <SurfaceFrame
      title="Tasks"
      subtitle="Scheduled automations Hermes runs for you"
      actions={
        <>
          <Button variant="ghost" size="icon-sm" aria-label="Refresh" onClick={jobs.reload}>
            <IconRefresh size={15} />
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              showSurface('chat')
              void sendPrompt('Help me set up a new scheduled task. Ask me what it should do and when it should run, then create it with the cronjob tool.')
            }}
          >
            New task
          </Button>
        </>
      }
    >
      {jobs.error && <ErrorNote message={jobs.error} onRetry={jobs.reload} />}
      {!jobs.error && rows.length === 0 && !jobs.loading && (
        <EmptyState icon={<IconCalendarClock />} title="No scheduled tasks" description="Ask Hermes to remind you, run a report, or check something every morning. Tasks run even while you are away." />
      )}
      <div className="flex flex-col">
        {rows.map(job => {
          const paused = job.state === 'paused' || job.enabled === false
          const next = toMs(job.next_run_at)
          const last = toMs(job.last_run_at)

          return (
            <div key={`${job.profile ?? ''}:${job.id}`} className="group flex items-center gap-4 border-b border-hairline py-3 last:border-b-0">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-[13px]">{job.name || job.prompt || job.id}</span>
                  <Badge tone={paused ? 'muted' : job.state === 'error' ? 'danger' : job.state === 'completed' ? 'ok' : 'accent'}>{job.state ?? (paused ? 'paused' : 'scheduled')}</Badge>
                  {job.profile && job.profile !== 'default' && <Badge tone="muted">{job.profile}</Badge>}
                </div>
                <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] text-fg-3">
                  <span>{job.schedule_display ?? job.schedule?.display ?? job.schedule?.expr ?? ''}</span>
                  {next && !paused && <span>next {formatRelative(next).replace(' ago', '')}</span>}
                  {last && <span>last {formatRelative(last)}{job.last_status ? ` · ${job.last_status}` : ''}</span>}
                  {job.deliver && <span>→ {job.deliver}</span>}
                </div>
                {job.last_error && <div className="mt-1 truncate text-[12px] text-danger">{job.last_error}</div>}
              </div>
              <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                <Button variant="ghost" size="icon-sm" aria-label="Run now" onClick={() => void act(job, 'trigger')}>
                  <IconRocket size={15} />
                </Button>
                <Button variant="ghost" size="icon-sm" aria-label={paused ? 'Resume' : 'Pause'} onClick={() => void act(job, paused ? 'resume' : 'pause')}>
                  {paused ? <IconPlayerPlay size={15} /> : <IconPlayerPause size={15} />}
                </Button>
                <Button variant="ghost" size="icon-sm" aria-label="Delete" onClick={() => void act(job, 'delete')}>
                  <IconTrash size={15} />
                </Button>
              </div>
            </div>
          )
        })}
      </div>
    </SurfaceFrame>
  )
}
