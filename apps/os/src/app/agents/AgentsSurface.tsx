import { useStore } from '@nanostores/react'
import { IconUsers } from '@tabler/icons-react'
import { Button } from '../../components/ui/button.tsx'
import { Badge, EmptyState, Spinner } from '../../components/ui/primitives.tsx'
import { SurfaceFrame } from '../../components/ui/surface-frame.tsx'
import { formatDuration, formatRelative } from '../../lib/format.ts'
import { $agents, type AgentActivity, clearFinishedAgents } from '../../store/agents.ts'
import { $chats } from '../../store/chat.ts'

const TONE: Record<AgentActivity['status'], 'accent' | 'ok' | 'danger' | 'muted'> = { running: 'accent', complete: 'ok', failed: 'danger', queued: 'muted' }

export function AgentsSurface() {
  const agents = useStore($agents)
  const chats = useStore($chats)
  const rows = Object.values(agents).sort((a, b) => b.updatedAt - a.updatedAt)
  const live = Object.values(chats).filter(chat => chat.streaming)

  return (
    <SurfaceFrame
      title="Agents"
      subtitle={`${live.length} session${live.length === 1 ? '' : 's'} working · ${rows.filter(r => r.status === 'running').length} subagents running`}
      actions={
        <Button variant="ghost" size="sm" onClick={clearFinishedAgents} disabled={rows.every(r => r.status === 'running' || r.status === 'queued')}>
          Clear finished
        </Button>
      }
    >
      {live.length > 0 && (
        <div className="mb-6 flex flex-col gap-1">
          <div className="px-1 text-[11px] tracking-[0.08em] text-fg-3 uppercase">Working now</div>
          {live.map(chat => (
            <div key={chat.sessionId} className="flex items-center gap-3 rounded-md px-3 py-2 hairline">
              <Spinner />
              <span className="min-w-0 flex-1 truncate text-[13px]">{chat.title || 'Untitled session'}</span>
              <span className="truncate text-[12px] text-fg-3">{chat.status?.text ?? 'Thinking'}</span>
            </div>
          ))}
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState icon={<IconUsers />} title="No subagents yet" description="When Hermes delegates work to parallel agents, their progress shows up here in real time." />
      ) : (
        <div className="flex flex-col gap-2">
          {rows.map(agent => (
            <div key={agent.id} className="flex flex-col gap-2 rounded-lg px-4 py-3 hairline">
              <div className="flex items-center gap-3">
                <Badge tone={TONE[agent.status]}>{agent.status}</Badge>
                <span className="min-w-0 flex-1 truncate text-[13px]">{agent.goal}</span>
                <span className="text-[11px] text-fg-4">{formatRelative(agent.updatedAt)}</span>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-fg-3">
                {agent.model && <span>{agent.model}</span>}
                {agent.toolName && <span>last tool: {agent.toolName}</span>}
                {agent.apiCalls != null && <span>{agent.apiCalls} calls</span>}
                {agent.inputTokens != null && <span>{agent.inputTokens.toLocaleString()} in / {(agent.outputTokens ?? 0).toLocaleString()} out</span>}
                {agent.durationSeconds != null && <span>{formatDuration(agent.durationSeconds)}</span>}
              </div>
              {(agent.summary || agent.lastText) && <div className="selectable line-clamp-3 text-[12.5px] text-fg-2">{agent.summary ?? agent.lastText}</div>}
            </div>
          ))}
        </div>
      )}
    </SurfaceFrame>
  )
}
