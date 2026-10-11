import { useEffect, useState } from 'react'
import type { PrivateApplicationSnapshot } from '../../../shared/missions.ts'
import { applicationSnapshot, applicationFrame, applicationState } from '../../../shared/application-view.ts'

export function PrivateApplications({ mission }: { mission: string }) {
  const [snapshot, setSnapshot] = useState<PrivateApplicationSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    let pending = false
    setSnapshot(null)
    const load = async () => {
      if (pending) return
      pending = true
      try {
        const value = applicationSnapshot(await window.heraldOS.missions.request('applications.snapshot', { id: mission }), mission)
        if (active) { setSnapshot(value); setError(null) }
      } catch (cause) {
        if (active) { setSnapshot(null); setError(cause instanceof Error ? cause.message : 'Application observations unavailable') }
      } finally { pending = false }
    }
    void load()
    const timer = setInterval(() => void load(), 2000)
    return () => { active = false; clearInterval(timer) }
  }, [mission])
  const current = snapshot?.mission === mission ? snapshot : null
  return <section className="flex flex-col gap-3" aria-label="Private mission applications">
    <h3 className="text-sm font-semibold text-fg">Private mission applications</h3>
    {error && <p role="status" className="text-xs text-warn">{error}</p>}
    {!error && !current && <p className="text-xs text-fg-4">Checking actual application receipts…</p>}
    {current && !current.authority_available && <p className="text-xs text-warn">Application observation service unavailable; saved receipts do not confirm a running process.</p>}
    {current?.applications.length === 0 && <p className="text-xs text-fg-4">No application admissions recorded for this mission.</p>}
    {current?.applications.map(app => {
      const frame = applicationFrame(app, current)
      return <figure key={app.instance} className="overflow-hidden rounded-lg border border-line">
        <figcaption className="flex flex-col gap-1 p-3 text-xs">
          <strong className="text-fg">Isolated mission application · {app.program}</strong>
          <span className="break-all font-mono text-fg-4">{mission} · {app.instance}</span>
          <span className="text-fg-3">{applicationState(app, current)}</span>
        </figcaption>
        {frame ? <><img src={frame} alt={`Actual private ${app.program} compositor capture`} draggable={false} decoding="async" className="pointer-events-none w-full select-none" /><p className="px-3 py-2 text-xs text-fg-4">Last verified capture · {new Date(app.capture_at! * 1000).toLocaleTimeString()}. Observation only; input is controlled by Hermes.</p></> : <p className="p-3 text-xs text-fg-4">No current capture available. Ask Hermes to show this application's workspace.</p>}
      </figure>
    })}
  </section>
}
