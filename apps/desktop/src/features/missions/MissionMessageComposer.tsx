import { useState } from 'react'
import { GlassButton } from '../../components/ui/glass.tsx'
import { submitMissionMessage } from '../../store/mission-conversation.ts'

/** Text stays editable until admission; an uncertain reply retains the same saved request intent. */
export function MissionMessageComposer() {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const send = async () => {
    if (!text.trim() || sending) return
    setSending(true)
    try {
      await submitMissionMessage(text)
      setText('')
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setSending(false)
    }
  }
  return (
    <div className="glass-card flex shrink-0 flex-col gap-2 rounded-xl p-3">
      <textarea value={text} onChange={event => setText(event.target.value)} disabled={sending} maxLength={32000} rows={2}
        aria-label="Message Hermes" placeholder="Describe what Hermes should do…"
        onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }}
        className="glass-input w-full resize-none rounded-lg px-3 py-2 text-sm text-fg" />
      {error && <p role="alert" className="text-xs text-danger">{error}. Your message remains here; retrying the same text reuses its submission.</p>}
      <div className="flex justify-end"><GlassButton size="sm" variant="primary" disabled={sending || !text.trim()} onClick={() => void send()}>{sending ? 'Sending…' : 'Send to Hermes'}</GlassButton></div>
    </div>
  )
}
