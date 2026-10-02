import { IconMessageChatbot, IconPlus, IconSparkles, IconX } from '@tabler/icons-react'
import { useState } from 'react'
import { GlassButton, GlassCard } from '../../components/ui/glass.tsx'
import { sendPrompt } from '../../store/chat.ts'
import { showPage } from '../../store/windows.ts'
import type { CronJobDraft, DeliveryTarget } from './api.ts'
import { SCHEDULE_FORMATS_HINT, SCHEDULE_PLACEHOLDER, humanizeCronExpr } from './cron-humanize.ts'
import { FieldLabel, GlyphTile, Hint, SelectInput, TextArea, TextInput, isLocalDelivery } from './presentation.tsx'

const DESCRIBE_PROMPT = 'Help me set up a new scheduled automation. Ask me what it should do and when, then create it with the cronjob tool.'

/** Inline "New automation" form shown in the detail column. */
export function NewAutomationForm({ targets, creating, onCreate, onCancel }: { targets: readonly DeliveryTarget[]; creating: boolean; onCreate: (draft: CronJobDraft) => Promise<boolean>; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [schedule, setSchedule] = useState('')
  const [prompt, setPrompt] = useState('')
  const [deliver, setDeliver] = useState('local')

  const canCreate = schedule.trim().length > 0 && prompt.trim().length > 0 && !creating
  const preview = humanizeCronExpr(schedule.trim())

  const submit = async () => {
    if (!canCreate) {
      return
    }

    await onCreate({ name: name.trim(), schedule: schedule.trim(), prompt: prompt.trim(), deliver })
  }

  return (
    <GlassCard className="flex h-full min-h-0 flex-col">
      <div className="flex items-start gap-3.5 px-5 pt-5 pb-4">
        <GlyphTile icon={<IconSparkles />} size={44} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[18px] leading-tight font-semibold text-fg">New automation</h2>
          <p className="mt-1 text-[12.5px] text-fg-3">Tell Hermes what to do and when. It runs even while you are away.</p>
        </div>
        <GlassButton size="icon" variant="ghost" onClick={onCancel} aria-label="Close new automation form" className="-mt-1 -mr-2">
          <IconX />
        </GlassButton>
      </div>

      <form
        className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 pb-4"
        onSubmit={event => {
          event.preventDefault()
          void submit()
        }}
      >
        <div className="flex flex-col gap-1.5">
          <FieldLabel htmlFor="new-automation-name">Name</FieldLabel>
          <TextInput id="new-automation-name" value={name} onChange={e => setName(e.target.value)} placeholder="Morning briefing" autoFocus />
        </div>

        <div className="flex flex-col gap-1.5">
          <FieldLabel htmlFor="new-automation-schedule">When</FieldLabel>
          <TextInput id="new-automation-schedule" value={schedule} onChange={e => setSchedule(e.target.value)} placeholder={SCHEDULE_PLACEHOLDER} required />
          <Hint>
            {preview ? (
              <span className="text-accent-strong">{preview}</span>
            ) : (
              <>
                Accepted: {SCHEDULE_FORMATS_HINT}.
              </>
            )}
          </Hint>
        </div>

        <div className="flex flex-col gap-1.5">
          <FieldLabel htmlFor="new-automation-prompt">What Hermes should do</FieldLabel>
          <TextArea id="new-automation-prompt" value={prompt} onChange={e => setPrompt(e.target.value)} rows={6} placeholder="Gather my calendar, priority mail and active missions, then write a short briefing for the day." required />
        </div>

        <div className="flex flex-col gap-1.5">
          <FieldLabel htmlFor="new-automation-deliver">Deliver to</FieldLabel>
          <SelectInput id="new-automation-deliver" value={deliver} onChange={e => setDeliver(e.target.value)}>
            {targets.map(target => (
              <option key={target.id} value={target.id} disabled={target.home_target_set === false}>
                {target.name}
                {target.home_target_set === false ? ' (set a home channel first)' : ''}
              </option>
            ))}
          </SelectInput>
          <Hint>{isLocalDelivery(deliver) ? 'Results are saved as a briefing you can open in Hermes.' : 'Hermes posts the result to the platform’s home channel when the run finishes.'}</Hint>
        </div>
      </form>

      <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3.5">
        <GlassButton
          variant="secondary"
          onClick={() => {
            showPage('hermes')
            void sendPrompt(DESCRIBE_PROMPT)
          }}
        >
          <IconMessageChatbot />
          Describe it to Hermes
        </GlassButton>
        <GlassButton variant="primary" disabled={!canCreate} onClick={() => void submit()} aria-label="Create automation">
          <IconPlus />
          {creating ? 'Creating…' : 'Create'}
        </GlassButton>
      </div>
    </GlassCard>
  )
}
