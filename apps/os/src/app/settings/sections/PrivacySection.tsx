import { IconHistory, IconShieldLock } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { GlassButton, GlassCard, LinkAction } from '../../../components/ui/glass.tsx'
import { deviceNoun } from '../../../lib/platform-labels.ts'
import { useLocalData } from '../../../lib/use-async.ts'
import { notify } from '../../../store/notifications.ts'
import { AuditRow } from './AgentsSection.tsx'
import { errorText, markSaved, SectionTitle, SettingsBlock, SettingsGroup, SettingsRow } from './shared.tsx'

/*
 * Privacy: the raw permission policy the Hermes OS bridge plugin enforces, plus the audit
 * trail. The textarea is the source of truth; the "Ask before sending" toggle in Hermes &
 * agents edits the same file line by line.
 */

export function PrivacySection() {
  const policy = useLocalData(() => window.hermesOS.bridge.readPolicy())
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [showAudit, setShowAudit] = useState(false)
  const audit = useLocalData(() => (showAudit ? window.hermesOS.bridge.readAudit(200) : Promise.resolve([])), [showAudit])
  const text = draft ?? policy.data ?? ''
  const dirty = draft !== null && draft !== policy.data

  useEffect(() => {
    setDraft(null)
  }, [policy.data])

  const save = async () => {
    setSaving(true)

    try {
      await window.hermesOS.bridge.writePolicy(text)
      markSaved()
      notify({ title: 'Permissions saved', body: 'The system bridge reads the policy on its next action.', level: 'success' })
      policy.reload()
    } catch (error) {
      notify({ title: 'Could not save policy', body: errorText(error), level: 'error' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <SectionTitle title="Privacy" subtitle={`What the system bridge may do on this ${deviceNoun()}, and the record of what it did.`} />

      <SettingsBlock title="Permission policy" label="Permission policy" description="Tiers: read runs freely, act runs and is audited, mutate asks first, destructive always asks. Protected paths are never touched." keywords="permissions yaml tiers allow confirm deny bridge">
        <GlassCard className="flex flex-col gap-3 p-3.5">
          <div className="text-[12px] leading-snug text-fg-3">
            Tiers: <span className="text-fg-2">read</span> runs freely, <span className="text-fg-2">act</span> runs and is audited, <span className="text-fg-2">mutate</span> asks first, <span className="text-fg-2">destructive</span> always asks. Each tier takes <span className="font-mono text-fg-2">allow</span>, <span className="font-mono text-fg-2">confirm</span> or <span className="font-mono text-fg-2">deny</span>.
          </div>
          <textarea
            value={text}
            onChange={event => setDraft(event.target.value)}
            spellCheck={false}
            aria-label="Permission policy"
            className="glass-input min-h-[260px] resize-y rounded-lg p-3 font-mono text-[12px] leading-relaxed text-fg-2 outline-none"
          />
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11.5px] text-fg-4">{policy.error ? policy.error : dirty ? 'Unsaved changes' : 'Saved on disk'}</span>
            <div className="flex items-center gap-2">
              <GlassButton size="sm" variant="ghost" disabled={!dirty} onClick={() => setDraft(null)}>
                Revert
              </GlassButton>
              <GlassButton size="sm" variant="primary" disabled={!dirty || saving} onClick={() => void save()}>
                Save policy
              </GlassButton>
            </div>
          </div>
        </GlassCard>
      </SettingsBlock>

      <SettingsGroup title="Protected paths">
        <SettingsRow
          icon={<IconShieldLock />}
          label="Protected paths"
          description="Paths listed under protected_paths are never read, written or moved by the bridge, whatever the tier says. Hermes's own config.yaml and secrets are protected upstream regardless."
          keywords="secrets config.yaml never touched"
        />
      </SettingsGroup>

      <SettingsGroup title="Audit">
        <SettingsRow
          icon={<IconHistory />}
          label="Audit log"
          description="Every action the bridge took or refused, newest first."
          keywords="history activity"
          below={
            showAudit ? (
              <div className="animate-rise flex max-h-[360px] flex-col overflow-y-auto rounded-lg border border-line bg-black/20">
                {audit.loading && !audit.data?.length && <div className="p-3 text-[12px] text-fg-4">Loading…</div>}
                {!audit.loading && (audit.data?.length ?? 0) === 0 && <div className="p-3 text-[12px] text-fg-4">No bridge activity yet.</div>}
                {(audit.data ?? []).map((entry, index) => (
                  <AuditRow key={`${entry.ts}-${index}`} entry={entry} />
                ))}
              </div>
            ) : undefined
          }
        >
          {showAudit && (
            <GlassButton size="sm" variant="ghost" onClick={audit.reload}>
              Refresh
            </GlassButton>
          )}
          <LinkAction onClick={() => setShowAudit(o => !o)}>{showAudit ? 'Hide log' : 'View log'}</LinkAction>
        </SettingsRow>
      </SettingsGroup>
    </>
  )
}
