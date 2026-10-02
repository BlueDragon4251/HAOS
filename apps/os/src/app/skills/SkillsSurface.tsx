import type { AgentPluginRow } from '@herald-os/client'
import { IconBolt, IconRefresh } from '@tabler/icons-react'
import { useMemo, useState } from 'react'
import { Button } from '../../components/ui/button.tsx'
import { Badge, EmptyState, Switch } from '../../components/ui/primitives.tsx'
import { ErrorNote, SurfaceFrame } from '../../components/ui/surface-frame.tsx'
import { cn } from '../../lib/cn.ts'
import { rest, type SkillRow } from '../../lib/rest.ts'
import { useBackendData } from '../../lib/use-async.ts'
import { gatewayRequest } from '../../store/gateway.ts'
import { notify } from '../../store/notifications.ts'

type Tab = 'skills' | 'plugins'

export function SkillsSurface() {
  const [tab, setTab] = useState<Tab>('skills')
  const [query, setQuery] = useState('')
  const skills = useBackendData(() => rest.get<SkillRow[]>('/api/skills'))
  const plugins = useBackendData(() => gatewayRequest('plugins.manage', { action: 'list' }).then(result => result.plugins ?? []))

  const filteredSkills = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const rows = skills.data ?? []

    return (needle ? rows.filter(s => s.name.toLowerCase().includes(needle) || (s.description ?? '').toLowerCase().includes(needle) || (s.category ?? '').toLowerCase().includes(needle)) : rows).sort((a, b) => a.name.localeCompare(b.name))
  }, [query, skills.data])

  const grouped = useMemo(() => {
    const map = new Map<string, SkillRow[]>()

    for (const skill of filteredSkills) {
      const key = skill.category || 'other'
      map.set(key, [...(map.get(key) ?? []), skill])
    }

    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [filteredSkills])

  const toggleSkill = async (skill: SkillRow, enabled: boolean) => {
    try {
      await rest.put('/api/skills/toggle', { name: skill.name, enabled })
      skills.reload()
    } catch (error) {
      notify({ title: 'Could not update skill', body: error instanceof Error ? error.message : String(error), level: 'error' })
    }
  }

  const togglePlugin = async (plugin: AgentPluginRow, enable: boolean) => {
    try {
      await gatewayRequest('plugins.manage', { action: 'toggle', key: plugin.key, name: plugin.name, enable })
      notify({ title: plugin.name, body: `${enable ? 'Enabled' : 'Disabled'}. Takes effect for new sessions.`, level: 'success' })
      plugins.reload()
    } catch (error) {
      notify({ title: 'Could not update plugin', body: error instanceof Error ? error.message : String(error), level: 'error' })
    }
  }

  return (
    <SurfaceFrame
      title="Skills"
      subtitle="What Hermes knows how to do"
      actions={
        <>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Filter" className="h-7 w-48 rounded-sm bg-surface px-2.5 text-[12.5px] outline-none hairline placeholder:text-fg-4 focus:shadow-[0_0_0_1px_var(--color-accent)]" />
          <div className="flex rounded-sm bg-surface p-0.5 hairline">
            {(['skills', 'plugins'] as Tab[]).map(id => (
              <button key={id} type="button" onClick={() => setTab(id)} className={cn('h-6 rounded-xs px-2.5 text-[12px] capitalize', tab === id ? 'bg-surface-3 text-fg' : 'text-fg-3 hover:text-fg-2')}>
                {id}
              </button>
            ))}
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="Refresh" onClick={() => (tab === 'skills' ? skills.reload() : plugins.reload())}>
            <IconRefresh size={15} />
          </Button>
        </>
      }
    >
      {tab === 'skills' ? (
        <>
          {skills.error && <ErrorNote message={skills.error} onRetry={skills.reload} />}
          {!skills.error && filteredSkills.length === 0 && !skills.loading && <EmptyState icon={<IconBolt />} title="No skills match" />}
          <div className="flex flex-col gap-6">
            {grouped.map(([category, rows]) => (
              <section key={category}>
                <div className="mb-1 px-1 text-[11px] tracking-[0.08em] text-fg-3 uppercase">{category}</div>
                {rows.map(skill => (
                  <div key={skill.name} className="flex items-center gap-4 border-b border-hairline py-2.5 last:border-b-0">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[12.5px]">/{skill.name}</span>
                        {skill.provenance && skill.provenance !== 'bundled' && <Badge tone={skill.provenance === 'hub' ? 'info' : 'accent'}>{skill.provenance}</Badge>}
                        {skill.usage ? <span className="text-[11px] text-fg-4">used {skill.usage}×</span> : null}
                      </div>
                      {skill.description && <div className="mt-0.5 truncate text-[12px] text-fg-3">{skill.description}</div>}
                    </div>
                    <Switch checked={skill.enabled !== false} onChange={next => void toggleSkill(skill, next)} label={`Toggle ${skill.name}`} />
                  </div>
                ))}
              </section>
            ))}
          </div>
        </>
      ) : (
        <>
          {plugins.error && <ErrorNote message={plugins.error} onRetry={plugins.reload} />}
          {!plugins.error && (plugins.data ?? []).length === 0 && !plugins.loading && <EmptyState icon={<IconBolt />} title="No plugins installed" />}
          <div className="flex flex-col">
            {(plugins.data ?? [])
              .filter(plugin => !query || plugin.name.toLowerCase().includes(query.toLowerCase()))
              .map(plugin => {
                const enabled = plugin.status !== 'disabled'

                return (
                  <div key={plugin.key} className="flex items-center gap-4 border-b border-hairline py-2.5 last:border-b-0">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[13px]">{plugin.name}</span>
                        <span className="text-[11px] text-fg-4">{plugin.version}</span>
                        <Badge tone={plugin.source === 'bundled' ? 'muted' : 'accent'}>{plugin.source}</Badge>
                        {plugin.key === 'herald-os-bridge' && <Badge tone="ok">system bridge</Badge>}
                        {plugin.update_available && <Badge tone="info">update</Badge>}
                      </div>
                      {plugin.description && <div className="mt-0.5 truncate text-[12px] text-fg-3">{plugin.description}</div>}
                    </div>
                    <Switch checked={enabled} onChange={next => void togglePlugin(plugin, next)} label={`Toggle ${plugin.name}`} />
                  </div>
                )
              })}
          </div>
        </>
      )}
    </SurfaceFrame>
  )
}
