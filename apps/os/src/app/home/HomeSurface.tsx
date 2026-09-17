import { useStore } from '@nanostores/react'
import { IconArrowRight, IconCalendarClock, IconMessage } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { BrandMark } from '../../components/brand-mark.tsx'
import { Meter, SectionTitle } from '../../components/ui/primitives.tsx'
import { formatBytes, formatDate, formatDuration, formatPercent, formatRelative, greetingFor } from '../../lib/format.ts'
import { type CronJob, rest } from '../../lib/rest.ts'
import { useBackendData } from '../../lib/use-async.ts'
import { $agents } from '../../store/agents.ts'
import { openStoredSession, runSlash, sendPrompt } from '../../store/chat.ts'
import { $connection } from '../../store/gateway.ts'
import { $sessions } from '../../store/sessions.ts'
import { showSurface } from '../../store/surface.ts'
import { useSystemInfo, useSystemStats } from '../../store/system.ts'
import { Composer } from '../chat/Composer.tsx'

export function HomeSurface() {
  const sessions = useStore($sessions)
  const connection = useStore($connection)
  const agents = useStore($agents)
  const stats = useSystemStats()
  const info = useSystemInfo()
  const jobs = useBackendData(() => rest.get<CronJob[]>('/api/cron/jobs'))
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60_000)

    return () => clearInterval(timer)
  }, [])

  const online = connection === 'open'
  const running = Object.values(agents).filter(a => a.status === 'running' || a.status === 'queued')
  const upcoming = (jobs.data ?? []).filter(job => job.enabled !== false && job.state !== 'completed').slice(0, 4)
  const firstName = info?.userName ? info.userName.split(/[._\-\s]/)[0] : ''
  const greeting = `${greetingFor(now)}${firstName ? `, ${firstName.charAt(0).toUpperCase()}${firstName.slice(1)}` : ''}`

  const submit = async (text: string) => {
    showSurface('chat')
    await (text.startsWith('/') ? runSlash(text) : sendPrompt(text))
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-8 pt-[9vh] pb-10">
        <div className="flex flex-col items-center gap-5 text-center">
          <BrandMark size={40} />
          <div>
            <h1 className="text-[28px] font-medium tracking-tight">{greeting}</h1>
            <div className="mt-1 text-[13px] text-fg-3">{formatDate(now)}</div>
          </div>
          <div className="w-full max-w-2xl">
            <Composer autoFocus disabled={!online} placeholder={online ? 'What would you like to do?' : 'Starting Hermes…'} onSubmit={submit} />
          </div>
        </div>

        <div className="mt-12 grid grid-cols-3 gap-8">
          <section className="flex flex-col gap-3">
            <SectionTitle action={<LinkButton onClick={() => showSurface('chat')}>All</LinkButton>}>Recent</SectionTitle>
            <div className="flex flex-col">
              {sessions.length === 0 && <Quiet>No sessions yet</Quiet>}
              {sessions.slice(0, 5).map(session => (
                <button
                  key={session.id}
                  type="button"
                  onClick={() => {
                    showSurface('chat')
                    void openStoredSession(session.id)
                  }}
                  className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-white/4"
                >
                  <IconMessage size={14} className="shrink-0 text-fg-4" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg-2">{session.title || session.preview || 'Untitled'}</span>
                  <span className="shrink-0 text-[11px] text-fg-4">{formatRelative(session.started_at)}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <SectionTitle action={<LinkButton onClick={() => showSurface('tasks')}>All</LinkButton>}>Tasks</SectionTitle>
            <div className="flex flex-col">
              {running.map(agent => (
                <div key={agent.id} className="flex items-center gap-2.5 rounded-md px-2 py-1.5">
                  <span className="size-1.5 shrink-0 rounded-full bg-accent animate-pulse-soft" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg-2">{agent.goal}</span>
                  <span className="shrink-0 text-[11px] text-fg-4">agent</span>
                </div>
              ))}
              {upcoming.map(job => (
                <button key={job.id} type="button" onClick={() => showSurface('tasks')} className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-white/4">
                  <IconCalendarClock size={14} className="shrink-0 text-fg-4" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg-2">{job.name || job.prompt}</span>
                  <span className="shrink-0 text-[11px] text-fg-4">{job.schedule_display ?? job.schedule?.display ?? ''}</span>
                </button>
              ))}
              {running.length === 0 && upcoming.length === 0 && <Quiet>Nothing scheduled</Quiet>}
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <SectionTitle action={<LinkButton onClick={() => showSurface('system')}>Details</LinkButton>}>System</SectionTitle>
            {stats ? (
              <div className="flex flex-col gap-3 px-2">
                <Gauge label="CPU" value={stats.cpuPercent} text={formatPercent(stats.cpuPercent)} />
                <Gauge label="Memory" value={(stats.memoryUsed / stats.memoryTotal) * 100} text={`${formatBytes(stats.memoryUsed, 0)} of ${formatBytes(stats.memoryTotal, 0)}`} />
                {stats.disks[0] && <Gauge label="Disk" value={(stats.disks[0].used / stats.disks[0].total) * 100} text={`${formatBytes(stats.disks[0].free, 0)} free`} />}
                <div className="flex justify-between text-[11.5px] text-fg-4">
                  <span>Up {formatDuration(stats.uptimeSeconds)}</span>
                  {info && <span>{info.osName} {info.osVersion}</span>}
                </div>
              </div>
            ) : (
              <Quiet>Sampling</Quiet>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function Gauge({ label, value, text }: { label: string; value: number; text: string }) {
  const tone = value > 90 ? 'danger' : value > 75 ? 'warn' : 'accent'

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between text-[12px]">
        <span className="text-fg-2">{label}</span>
        <span className="tabular-nums text-fg-3">{text}</span>
      </div>
      <Meter value={value} tone={tone} />
    </div>
  )
}

function Quiet({ children }: { children: React.ReactNode }) {
  return <div className="px-2 py-1.5 text-[12px] text-fg-4">{children}</div>
}

function LinkButton({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="flex items-center gap-0.5 text-[11px] text-fg-3 hover:text-fg-2">
      {children}
      <IconArrowRight size={11} />
    </button>
  )
}
