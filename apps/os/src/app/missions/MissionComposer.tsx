import { IconRocket } from '@tabler/icons-react'
import { useState } from 'react'
import { GlassButton } from '../../components/ui/glass.tsx'
import { createChat, sendPrompt } from '../../store/chat.ts'
import { notify } from '../../store/notifications.ts'
import { showPage } from '../../store/windows.ts'

const TITLE_MAX = 60

function missionPrompt(text: string): string {
  return `Mission: ${text}\n\nPlan this as a mission: first create a todo list of the concrete steps with the todo tool, then work through them, updating the todo list as you go, and finish with a short summary of what you produced.`
}

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
      const chat = await createChat({ title: goal.slice(0, TITLE_MAX) })
      void sendPrompt(missionPrompt(goal), { sessionId: chat.sessionId })
      showPage('hermes')
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
