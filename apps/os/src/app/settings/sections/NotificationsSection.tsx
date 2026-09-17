import { IconBellRinging, IconChecklist, IconDeviceDesktop, IconShieldCheck } from '@tabler/icons-react'
import { useState } from 'react'
import { Toggle } from '../../../components/ui/glass.tsx'
import { markSaved, readLocalFlag, SectionTitle, SettingsGroup, SettingsRow, writeLocal } from './shared.tsx'

/*
 * Notification preferences are shell-side flags in localStorage (`hermes-os.notify.*`). The
 * notification store does not read them yet; see the page report for the proposed wiring.
 */

export const NOTIFY_KEYS = {
  toolCompletions: 'hermes-os.notify.tool-completions',
  approvals: 'hermes-os.notify.approvals',
  taskUpdates: 'hermes-os.notify.task-updates',
  nativeWhenUnfocused: 'hermes-os.notify.native-unfocused'
} as const

type NotifyKey = keyof typeof NOTIFY_KEYS

const ROWS: { key: NotifyKey; label: string; description: string; icon: React.ReactNode; keywords?: string }[] = [
  { key: 'toolCompletions', label: 'Tool completions', description: 'A toast when a long-running tool finishes in a session you are not looking at.', icon: <IconChecklist />, keywords: 'toast finished' },
  { key: 'approvals', label: 'Approvals', description: 'Tell me when Hermes is waiting for a decision.', icon: <IconShieldCheck />, keywords: 'permission request waiting' },
  { key: 'taskUpdates', label: 'Task updates', description: 'Scheduled tasks that ran, failed or changed.', icon: <IconBellRinging />, keywords: 'cron automations' },
  { key: 'nativeWhenUnfocused', label: 'Native notifications when unfocused', description: 'Use macOS Notification Center while Hermes OS is in the background.', icon: <IconDeviceDesktop />, keywords: 'macos system background' }
]

export function NotificationsSection() {
  const [flags, setFlags] = useState<Record<NotifyKey, boolean>>(() => ({
    toolCompletions: readLocalFlag(NOTIFY_KEYS.toolCompletions, true),
    approvals: readLocalFlag(NOTIFY_KEYS.approvals, true),
    taskUpdates: readLocalFlag(NOTIFY_KEYS.taskUpdates, true),
    nativeWhenUnfocused: readLocalFlag(NOTIFY_KEYS.nativeWhenUnfocused, true)
  }))

  const set = (key: NotifyKey, value: boolean) => {
    setFlags(prev => ({ ...prev, [key]: value }))
    writeLocal(NOTIFY_KEYS[key], String(value))
    markSaved()
  }

  return (
    <>
      <SectionTitle title="Notifications" subtitle="These are Hermes OS shell preferences. They shape what the shell surfaces; Hermes itself keeps working either way." />

      <SettingsGroup title="Alerts">
        {ROWS.map(row => (
          <SettingsRow key={row.key} icon={row.icon} label={row.label} description={row.description} keywords={row.keywords}>
            <Toggle checked={flags[row.key]} onChange={next => set(row.key, next)} label={row.label} />
          </SettingsRow>
        ))}
      </SettingsGroup>
    </>
  )
}
