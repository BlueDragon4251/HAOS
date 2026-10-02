import { IconRocket } from '@tabler/icons-react'
import { useState } from 'react'
import { GlassButton } from '../../components/ui/glass.tsx'
import { startMission } from '../../store/missions-actions.ts'
import { notify } from '../../store/notifications.ts'

export function MissionComposer({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState('')
  const [starting, setStarting] = useState(false)
  const ready = text.trim().length > 0 && !starting

  const start = async () => {
    const goal = text.trim()

    if (!goal || starting) {
      return
    }

    setStarting(true)

    try {
      await startMission(goal)
      onClose()
    } catch (error) {
      notify({ title: 'Could not start mission', body: error instanceof Error ? error.message : String(error), level: 'error' })
      setStarting(false)
    }
  }

  return (
    <div className="glass-card animate-rise flex flex-col gap-3 rounded-xl p-4">
      <div className="flex items-center gap-2 text-[14px] font-semibold text-fg">
        <IconRocket size={16} className="text-accent-strong" />
        New mission
      </div>
      <textarea
        value={text}
        autoFocus
        rows={3}
        onChange={event => setText(event.target.value)}
        onKeyDown={event => {
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
            event.preventDefault()
            void start()
          }

          if (event.key === 'Escape') {
            onClose()
          }
        }}
        placeholder="What should Hermes accomplish?"
        aria-label="Mission goal"
        className="glass-input w-full resize-none rounded-lg px-3 py-2.5 text-[13px] text-fg outline-none placeholder:text-fg-4"
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] text-fg-4">Hermes plans the steps, works through them and reports back.</span>
        <div className="flex items-center gap-2">
          <GlassButton size="sm" variant="ghost" onClick={onClose} disabled={starting}>
            Cancel
          </GlassButton>
          <GlassButton size="sm" variant="primary" onClick={() => void start()} disabled={!ready}>
            {starting ? 'Starting…' : 'Start mission'}
          </GlassButton>
        </div>
      </div>
    </div>
  )
}
