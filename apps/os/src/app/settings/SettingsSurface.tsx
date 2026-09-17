import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useState } from 'react'
import type { AuditEntry } from '../../../shared/ipc.ts'
import { Button } from '../../components/ui/button.tsx'
import { Badge, Row, Switch } from '../../components/ui/primitives.tsx'
import { ErrorNote, SurfaceFrame } from '../../components/ui/surface-frame.tsx'
import { cn } from '../../lib/cn.ts'
import { formatRelative } from '../../lib/format.ts'
import { useBackendData, useLocalData } from '../../lib/use-async.ts'
import { $backend, $env, $prefs, updatePrefs } from '../../store/backend.ts'
import { $activeChat } from '../../store/chat.ts'
import { $connection, gatewayRequest } from '../../store/gateway.ts'
import { notify } from '../../store/notifications.ts'

type Section = 'general' | 'model' | 'permissions' | 'backend'

const SECTIONS: { id: Section; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'model', label: 'Model' },
  { id: 'permissions', label: 'Permissions' },
  { id: 'backend', label: 'Hermes runtime' }
]

export function SettingsSurface() {
  const [section, setSection] = useState<Section>('general')

  return (
    <div className="flex h-full">
      <aside className="flex w-52 shrink-0 flex-col gap-0.5 border-r border-hairline px-2 py-3">
        <div className="mb-1 px-2 text-[11px] tracking-[0.08em] text-fg-3 uppercase">Settings</div>
        {SECTIONS.map(item => (
          <button key={item.id} type="button" onClick={() => setSection(item.id)} className={cn('flex h-7 items-center rounded-md px-2 text-left text-[12.5px]', section === item.id ? 'bg-white/6 text-fg' : 'text-fg-2 hover:bg-white/4')}>
            {item.label}
          </button>
        ))}
      </aside>
      <div className="min-w-0 flex-1">
        {section === 'general' && <GeneralSettings />}
        {section === 'model' && <ModelSettings />}
        {section === 'permissions' && <PermissionSettings />}
        {section === 'backend' && <BackendSettings />}
      </div>
    </div>
  )
}

function GeneralSettings() {
  const prefs = useStore($prefs)
  const env = useStore($env)

  return (
    <SurfaceFrame title="General" subtitle={env ? `Hermes OS ${env.version}` : undefined}>
      <div className="max-w-2xl divide-y divide-hairline">
        <Row title="Launch fullscreen" description="Hermes OS takes over the screen when it starts. Cmd+Ctrl+F toggles at any time.">
          <Switch checked={prefs.fullscreenOnLaunch} onChange={next => void updatePrefs({ fullscreenOnLaunch: next })} label="Launch fullscreen" />
        </Row>
        <Row title="Reduce motion" description="Disable non-essential animation.">
          <Switch checked={prefs.reduceMotion} onChange={next => void updatePrefs({ reduceMotion: next })} label="Reduce motion" />
        </Row>
        <Row title="Accent" description="The single accent colour used across the environment.">
          <div className="flex gap-1.5">
            {(['blue', 'ice', 'violet'] as const).map(accent => (
              <button
                key={accent}
                type="button"
                aria-label={accent}
                onClick={() => void updatePrefs({ accent })}
                className={cn('size-6 rounded-full transition-transform', prefs.accent === accent ? 'scale-110 shadow-[0_0_0_2px_var(--color-bg),0_0_0_3.5px_var(--color-fg-3)]' : 'opacity-70 hover:opacity-100')}
                style={{ background: accent === 'blue' ? '#2f7dff' : accent === 'ice' ? '#4cc2ff' : '#7c6cff' }}
              />
            ))}
          </div>
        </Row>
        <Row title="Quit Hermes OS" description="Stops the Hermes backend this shell started and returns to macOS.">
          <Button variant="danger" size="sm" onClick={() => void window.hermesOS.window.quit()}>
            Quit
          </Button>
        </Row>
      </div>
    </SurfaceFrame>
  )
}

function ModelSettings() {
  const chat = useStore($activeChat)
  const connection = useStore($connection)
  const options = useBackendData(() => gatewayRequest('model.options', { include_unconfigured: false }), [], { enabled: connection === 'open' })
  const [pending, setPending] = useState<string | null>(null)

  const current = options.data?.model ?? chat?.info.model
  const provider = options.data?.provider ?? chat?.info.provider

  const setModel = async (providerSlug: string, model: string) => {
    if (!chat) {
      notify({ title: 'Open a session first', body: 'Model changes apply to the active session and become the default for new ones.', level: 'info' })

      return
    }

    setPending(`${providerSlug}:${model}`)

    try {
      await gatewayRequest('slash.exec', { session_id: chat.sessionId, command: `/model ${providerSlug}:${model}` })
      notify({ title: 'Model changed', body: `${providerSlug} · ${model}`, level: 'success' })
      options.reload()
    } catch (error) {
      notify({ title: 'Could not change model', body: error instanceof Error ? error.message : String(error), level: 'error' })
    } finally {
      setPending(null)
    }
  }

  return (
    <SurfaceFrame title="Model" subtitle={current ? `${provider ?? ''} · ${current}` : undefined}>
      {options.error && <ErrorNote message={options.error} onRetry={options.reload} />}
      <div className="flex max-w-3xl flex-col gap-6">
        {(options.data?.providers ?? [])
          .filter(p => (p.models?.length ?? 0) > 0)
          .map(p => (
            <section key={p.slug}>
              <div className="mb-1.5 flex items-center gap-2 px-1">
                <span className="text-[12px] font-medium text-fg-2">{p.name}</span>
                {p.is_current && <Badge tone="accent">current</Badge>}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(p.models ?? []).slice(0, 40).map(model => {
                  const active = p.is_current && model === current
                  const busy = pending === `${p.slug}:${model}`

                  return (
                    <button key={model} type="button" disabled={Boolean(pending)} onClick={() => void setModel(p.slug, model)} className={cn('rounded-sm px-2.5 py-1 font-mono text-[12px] transition-colors', active ? 'bg-accent text-accent-fg' : 'bg-surface text-fg-2 hairline hover:bg-surface-2 hover:text-fg', busy && 'opacity-60')}>
                      {model}
                    </button>
                  )
                })}
                {(p.total_models ?? 0) > 40 && <span className="self-center px-1 text-[11px] text-fg-4">+{(p.total_models ?? 0) - 40} more via /model</span>}
              </div>
            </section>
          ))}
      </div>
    </SurfaceFrame>
  )
}

/** `tools.tool_search.enabled`: upstream defers plugin tools behind a search bridge; "off" keeps the system tools directly callable. */
function DirectToolsRow() {
  const connection = useStore($connection)
  const setting = useBackendData(() => gatewayRequest('config.get', { key: 'tools.tool_search.enabled' }), [], { enabled: connection === 'open' })
  const [busy, setBusy] = useState(false)
  const direct = String(setting.data?.value ?? 'auto').toLowerCase() === 'off'

  const toggle = async (next: boolean) => {
    setBusy(true)

    try {
      await gatewayRequest('config.set', { key: 'tools.tool_search.enabled', value: next ? 'off' : 'auto' })
      notify({ title: next ? 'System tools are direct' : 'System tools are deferred', body: 'Restart Hermes for running sessions to pick this up.', level: 'success' })
      setting.reload()
    } catch (error) {
      notify({ title: 'Could not change setting', body: error instanceof Error ? error.message : String(error), level: 'error' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Row
      title="Direct system tools"
      description="Keep the Hermes OS tools in every session's tool list so Hermes reaches for them first. Off defers them behind Hermes's tool search (fewer prompt tokens, but the agent tends to fall back to shell commands)."
    >
      <Switch checked={direct} onChange={next => void toggle(next)} label="Direct system tools" />
      {busy && <span className="text-[11px] text-fg-4">saving</span>}
    </Row>
  )
}

function PermissionSettings() {
  const policy = useLocalData(() => window.hermesOS.bridge.readPolicy())
  const audit = useLocalData(() => window.hermesOS.bridge.readAudit(200))
  const [draft, setDraft] = useState<string | null>(null)
  const text = draft ?? policy.data ?? ''
  const dirty = draft !== null && draft !== policy.data

  useEffect(() => {
    setDraft(null)
  }, [policy.data])

  const save = async () => {
    try {
      await window.hermesOS.bridge.writePolicy(text)
      notify({ title: 'Permissions saved', body: 'The system bridge reads the policy on its next action.', level: 'success' })
      policy.reload()
    } catch (error) {
      notify({ title: 'Could not save policy', body: error instanceof Error ? error.message : String(error), level: 'error' })
    }
  }

  const grouped = useMemo(() => audit.data ?? [], [audit.data])

  return (
    <SurfaceFrame
      title="Permissions"
      subtitle="How the system bridge may act on this Mac"
      actions={
        <>
          <Button variant="ghost" size="sm" onClick={audit.reload}>
            Refresh log
          </Button>
          <Button variant="primary" size="sm" disabled={!dirty} onClick={() => void save()}>
            Save policy
          </Button>
        </>
      }
    >
      <div className="mb-6 max-w-5xl divide-y divide-hairline">
        <DirectToolsRow />
      </div>
      <div className="grid max-w-5xl grid-cols-2 gap-8">
        <section className="flex flex-col gap-2">
          <div className="text-[12px] text-fg-3">
            Tiers: <span className="text-fg-2">read</span> runs freely, <span className="text-fg-2">act</span> runs and is audited, <span className="text-fg-2">mutate</span> asks first, <span className="text-fg-2">destructive</span> always asks. Protected paths are never touched.
          </div>
          <textarea value={text} onChange={event => setDraft(event.target.value)} spellCheck={false} className="min-h-[360px] flex-1 resize-y rounded-md bg-surface p-3 font-mono text-[12px] leading-relaxed text-fg-2 outline-none hairline focus:shadow-[0_0_0_1px_var(--color-accent)]" />
        </section>
        <section className="flex min-h-0 flex-col gap-2">
          <div className="text-[12px] text-fg-3">Audit trail: every action the bridge took or was refused, newest first.</div>
          <div className="flex max-h-[520px] flex-col overflow-y-auto rounded-md hairline">
            {grouped.length === 0 && <div className="p-4 text-[12px] text-fg-4">No bridge activity yet.</div>}
            {grouped.map((entry, index) => (
              <AuditRow key={`${entry.ts}-${index}`} entry={entry} />
            ))}
          </div>
        </section>
      </div>
    </SurfaceFrame>
  )
}

function AuditRow({ entry }: { entry: AuditEntry }) {
  const tone = !entry.ok ? 'danger' : entry.decision === 'denied' || entry.decision === 'blocked' ? 'warn' : entry.tier === 'destructive' ? 'warn' : 'muted'

  return (
    <div className="flex items-start gap-3 border-b border-hairline px-3 py-2 text-[12px] last:border-b-0">
      <span className="w-14 shrink-0 text-fg-4">{formatRelative(Date.parse(entry.ts))}</span>
      <span className="w-36 shrink-0 truncate font-mono text-fg-2">{entry.tool}{entry.action ? `.${entry.action}` : ''}</span>
      <Badge tone={tone}>{entry.decision}</Badge>
      <span className="selectable min-w-0 flex-1 truncate text-fg-3">{entry.summary ?? entry.error ?? ''}</span>
    </div>
  )
}

function BackendSettings() {
  const backend = useStore($backend)
  const connection = useStore($connection)
  const [log, setLog] = useState<string[]>([])

  const loadLog = () => void window.hermesOS.backend.logTail(300).then(setLog)

  useEffect(loadLog, [backend.phase])

  return (
    <SurfaceFrame
      title="Hermes runtime"
      subtitle={backend.runtime?.label}
      actions={
        <>
          <Button variant="ghost" size="sm" onClick={loadLog}>
            Refresh log
          </Button>
          <Button variant="secondary" size="sm" onClick={() => void window.hermesOS.backend.restart()}>
            Restart Hermes
          </Button>
        </>
      }
    >
      <div className="max-w-3xl divide-y divide-hairline">
        <Row title="Backend" description={backend.baseUrl ?? 'not running'}>
          <Badge tone={backend.phase === 'ready' ? 'ok' : backend.phase === 'failed' ? 'danger' : 'warn'}>{backend.phase}</Badge>
        </Row>
        <Row title="Gateway socket" description="JSON-RPC over WebSocket">
          <Badge tone={connection === 'open' ? 'ok' : 'warn'}>{connection}</Badge>
        </Row>
        <Row title="Runtime" description={backend.runtime ? backend.runtime.command.join(' ') : '—'}>
          {backend.runtime && <Badge tone="muted">{backend.runtime.kind}</Badge>}
        </Row>
        <Row title="Update Hermes" description="Hermes OS runs whatever `hermes update` installs. Run it in the Terminal, then restart Hermes here." />
      </div>
      {backend.error && <div className="mt-4"><ErrorNote message={backend.error} /></div>}
      <pre className="selectable mt-6 max-h-[420px] overflow-auto rounded-md bg-surface p-3 font-mono text-[11px] leading-relaxed text-fg-3 hairline">{log.join('\n') || 'No log output yet.'}</pre>
    </SurfaceFrame>
  )
}
