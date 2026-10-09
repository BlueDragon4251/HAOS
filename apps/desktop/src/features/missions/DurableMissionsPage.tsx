import { useStore } from '@nanostores/react'
import { IconPlus, IconTarget } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import type { DurableMissionState, MissionQuestion } from '../../../shared/missions.ts'
import { EmptyGlass, GlassButton, GlassCard, PageHeader } from '../../components/ui/glass.tsx'
import { $durableMissions, $missionEvents, $missionServiceError, $missionServiceHealth, loadMissionEvents, refreshDurableMissions } from '../../store/durable-missions.ts'
import { $missionFocus } from '../../store/missions.ts'
import { notify } from '../../store/notifications.ts'
import { runCommand } from '../../store/os-commands.ts'
import { MissionComposer } from './MissionComposer.tsx'
import { $pendingMissionMessages, recoverMissionMessages } from '../../store/mission-conversation.ts'
import { MissionMessageComposer } from './MissionMessageComposer.tsx'
import { SystemHealth } from './SystemHealth.tsx'

const STATE_COLOR: Record<DurableMissionState, string> = {
  queued: 'text-fg-3', running: 'text-progress', waiting: 'text-warn', blocked: 'text-warn',
  failed: 'text-danger', completed: 'text-ok', cancelled: 'text-fg-4'
}
const ACTIVE = new Set<DurableMissionState>(['queued', 'running', 'waiting'])

async function command(id: string, args: Record<string, unknown>): Promise<void> {
  const result = await runCommand(id, args, { source: 'ui' })
  if (!result.ok) notify({ title: 'Mission action failed', body: result.error || result.summary, level: 'error' })
}

function PendingQuestion({ question }: { question: MissionQuestion }) {
  const [answer, setAnswer] = useState('')
  const [sending, setSending] = useState(false)
  const respond = async (choice?: 'once' | 'deny') => {
    setSending(true)
    try {
      await command('mission.answer', { requestId: String(question.id), choice, answer: choice ? undefined : answer })
    } finally {
      setSending(false)
    }
  }
  return (
    <section className="flex flex-col gap-3 border-b border-line pb-4" aria-label="Mission needs an answer">
      <h3 className="text-sm font-semibold text-warn">{question.method === 'approval' ? 'Tool approval' : 'Clarification'}</h3>
      <p className="whitespace-pre-wrap text-xs text-fg-2">{question.params.description || question.params.command || JSON.stringify(question.params, null, 2)}</p>
      {question.method === 'approval' ? (
        <div className="flex gap-2">
          {question.params.choices?.includes('once') && <GlassButton size="sm" disabled={sending} onClick={() => void respond('once')}>Allow once</GlassButton>}
          {question.params.choices?.includes('deny') && <GlassButton size="sm" disabled={sending} onClick={() => void respond('deny')}>Deny</GlassButton>}
        </div>
      ) : (
        <>
          <textarea className="glass-input rounded-lg p-3 text-sm text-fg" aria-label="Clarification answer" value={answer} maxLength={16000} disabled={sending} onChange={event => setAnswer(event.target.value)} />
          <GlassButton size="sm" disabled={sending || !answer.trim()} onClick={() => void respond()}>Send answer</GlassButton>
        </>
      )}
      <p className="text-xs text-fg-4">This response grants no owner or storage authority.</p>
    </section>
  )
}

export function DurableMissionsPage({ conversation = false }: { conversation?: boolean }) {
  const missions = useStore($durableMissions)
  const health = useStore($missionServiceHealth)
  const error = useStore($missionServiceError)
  const allEvents = useStore($missionEvents)
  const focus = useStore($missionFocus)
  const pending = useStore($pendingMissionMessages)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [composing, setComposing] = useState(false)
  const [eventError, setEventError] = useState<string | null>(null)
  const [admissionError, setAdmissionError] = useState<string | null>(null)
  const selected = missions.find(row => row.id === selectedId) ?? missions[0] ?? null
  const id = selected?.id
  const events = id ? allEvents[id] ?? [] : []
  const questions = health?.pending_requests.filter(q => q.params.session_id === selected?.session_id) ?? []

  useEffect(() => {
    void refreshDurableMissions()
    const timer = setInterval(() => void refreshDurableMissions(), 2000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!conversation) return
    let active = true
    const recover = async () => {
      try { await recoverMissionMessages(); if (active) setAdmissionError(null) }
      catch (cause) { if (active) setAdmissionError(cause instanceof Error ? cause.message : String(cause)) }
    }
    void recover()
    const timer = setInterval(() => void recover(), 5000)
    return () => { active = false; clearInterval(timer) }
  }, [conversation])

  useEffect(() => {
    if (focus?.missionId) setSelectedId(focus.missionId)
    if (focus?.compose) setComposing(true)
  }, [focus])

  useEffect(() => {
    if (!id) return
    let active = true
    const load = async () => {
      try {
        await loadMissionEvents(id)
        if (active) setEventError(null)
      } catch (cause) {
        if (active) setEventError(cause instanceof Error ? cause.message : String(cause))
      }
    }
    void load()
    const timer = setInterval(() => void load(), 1500)
    return () => { active = false; clearInterval(timer) }
  }, [id])

  return (
    <div className="page-enter flex h-full flex-col">
      <PageHeader icon={conversation ? 'hermes' : 'missions'} title={conversation ? 'Hermes' : 'Missions'} subtitle="Durable work, supervised independently of this window."
        actions={<GlassButton onClick={() => void command('mission.compose', {})}><IconPlus />New mission</GlassButton>} />
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-6 pb-6">
        <p role="status" className={`text-xs ${error ? 'text-danger' : 'text-fg-3'}`}>
          {error ? `Controller unavailable: ${error}. Stored work is not resubmitted by the UI.` : health ? 'Mission controller connected' : 'Connecting to the mission controller…'}
        </p>
        {admissionError && <p role="alert" className="text-xs text-danger">Could not check pending messages: {admissionError}</p>}
        {pending.length > 0 && <p role="status" className="text-xs text-warn">{pending.length} submission receipt(s) pending. Hermes checks saved admissions without resending. To retry, enter the exact original message.</p>}
        <SystemHealth value={health?.system ?? null} />
        <div className="flex min-h-0 flex-1 gap-4">
          <div className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto">
            {missions.length === 0 ? <EmptyGlass icon={<IconTarget />} title="No queued missions" description="Give Hermes a goal. The controller records it before execution." /> : missions.map(row => (
              <button key={row.id} onClick={() => { setSelectedId(row.id); if (!conversation) void command('mission.openDurable', { id: row.id }) }}
                className={`flex flex-col gap-2 rounded-xl p-4 text-left ${selected?.id === row.id ? 'glass-card-selected' : 'glass-card-hover'}`}>
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate text-sm font-semibold text-fg">{row.goal.slice(0, 60)}</span>
                  <span className={`text-xs ${STATE_COLOR[row.state]}`}>{row.state}</span>
                </div>
                <p className="line-clamp-2 text-xs text-fg-3">{row.goal}</p>
                <span className="text-xs text-fg-4">Attempt {row.attempt}/{row.max_attempts} · {new Date(row.updated_at * 1000).toLocaleString()}</span>
              </button>
            ))}
          </div>
          <div className="flex w-[440px] shrink-0 flex-col gap-3">
            {composing && <MissionComposer onClose={() => setComposing(false)} />}
            <GlassCard className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
              {selected ? (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <h2 className="text-sm font-semibold text-fg">{selected.goal.slice(0, 60)}</h2>
                    {ACTIVE.has(selected.state) && <GlassButton size="sm" disabled={Boolean(selected.cancel_requested)} onClick={() => void command('mission.cancel', { id: selected.id })}>{selected.cancel_requested ? 'Stop requested' : 'Stop'}</GlassButton>}
                  </div>
                  <p className="whitespace-pre-wrap text-sm text-fg-2">{selected.goal}</p>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
                    <dt className="text-fg-4">State</dt><dd className={STATE_COLOR[selected.state]}>{selected.state}</dd>
                    <dt className="text-fg-4">Mission</dt><dd className="break-all font-mono text-fg-3">{selected.id}</dd>
                    <dt className="text-fg-4">Deadline</dt><dd className="text-fg-3">{new Date(selected.deadline * 1000).toLocaleString()}</dd>
                  </dl>
                  {selected.error && <p role="alert" className="whitespace-pre-wrap text-xs text-warn">{selected.error}</p>}
                  {selected.state === 'blocked' && <p className="text-xs text-warn">Execution may have changed files or external services. Owner recovery must inspect and reconcile it before another mission uses this workspace.</p>}
                  {questions.map(q => <PendingQuestion key={String(q.id)} question={q} />)}
                  {selected.result && <section className="flex flex-col gap-2"><h3 className="text-sm font-semibold text-fg">Hermes result</h3><p className="text-xs text-fg-4">Recorded upstream turn receipt. Review its evidence and remaining work.</p><pre className="whitespace-pre-wrap break-words text-xs text-fg-2">{selected.result}</pre></section>}
                  <section className="flex flex-col gap-3" aria-label="Recorded mission events">
                    <h3 className="text-sm font-semibold text-fg">Recorded activity</h3>
                    {eventError && <p role="alert" className="text-xs text-danger">Could not load events: {eventError}</p>}
                    {events.map(event => <details key={event.seq} className="border-l border-line pl-3"><summary className="flex cursor-pointer justify-between gap-2 text-xs"><span className="font-medium text-fg-2">{event.kind}</span><time className="text-fg-4">{new Date(event.at * 1000).toLocaleTimeString()}</time></summary><pre className="mt-1 whitespace-pre-wrap break-words text-[11px] text-fg-3">{JSON.stringify(event.payload, null, 2)}</pre></details>)}
                  </section>
                </>
              ) : <EmptyGlass icon={<IconTarget />} title="Select a mission" description="Its saved state, real Hermes events and result appear here." />}
            </GlassCard>
          </div>
        </div>
        {conversation && <MissionMessageComposer />}
      </div>
    </div>
  )
}
