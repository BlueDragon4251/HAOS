import { useStore } from '@nanostores/react'
import { IconDownload, IconFileText, IconInfoCircle, IconServer } from '@tabler/icons-react'
import { useState } from 'react'
import { GlassButton, Pill } from '../../../components/ui/glass.tsx'
import { type HermesStatusPayload, rest } from '../../../lib/rest.ts'
import { useBackendData, useLocalData } from '../../../lib/use-async.ts'
import { $backend, $env } from '../../../store/backend.ts'
import { openApp } from '../../../store/windows.ts'
import { AboutIdentity, BrandingSettings } from './BrandingSettings.tsx'
import { LogView, SectionTitle, SettingsGroup, SettingsRow } from './shared.tsx'

export function AboutSection() {
  const env = useStore($env)
  const backend = useStore($backend)
  const status = useBackendData(() => rest.get<HermesStatusPayload>('/api/status'))
  const [showLog, setShowLog] = useState(false)
  const updates = useLocalData(() => window.heraldOS.system.haosUpdate(), [])
  const log = useLocalData(() => (showLog ? window.heraldOS.backend.logTail(300) : Promise.resolve<string[]>([])), [showLog, backend.phase])

  return (
    <>
      <SectionTitle title="About" subtitle="Versions, the runtime underneath, your branding, and where to look when something is off." />

      <AboutIdentity />

      <SettingsGroup title="Versions">
        <SettingsRow icon={<IconInfoCircle />} label="HAOS" description={env?.isDev ? 'Development build.' : 'Agent-native operating system.'} keywords="version build shell">
          <Pill tone="accent">{env?.version ?? '—'}</Pill>
        </SettingsRow>
        <SettingsRow icon={<IconServer />} label="Hermes runtime" description={<span className="selectable">{backend.runtime?.label ?? 'Not resolved yet.'}</span>} keywords="hermes agent version runtime">
          <Pill>{status.data?.version && status.data.version !== 'unknown' ? `v${String(status.data.version).replace(/^v/, '')}` : status.loading ? '…' : 'unknown'}</Pill>
          {backend.runtime && <Pill>{backend.runtime.kind}</Pill>}
        </SettingsRow>
      </SettingsGroup>

      <BrandingSettings />

      <SettingsGroup title="Maintenance">
        <SettingsRow icon={<IconDownload />} label="HAOS system updates"
          description={updates.data ? `Channel: ${updates.data.channel} · ${updates.data.state}${updates.data.reboot_required ? ' · Restart to activate' : ''}` : 'Immutable bootc image updates'}
          keywords="upgrade update bootc ghcr token dev stable reboot"
          below={updates.data ? (
            <div className="mt-2 space-y-2 text-[12px] text-fg-3">
              <p>{updates.data.reboot_required ? 'A new OS image was staged. Restart when ready; the previous deployment remains available for rollback.' : updates.data.auto_stage ? 'Checks every six hours and stages newer images; never restarts without you.' : 'Automatic staging is disabled until an authenticated owner enables it.'}</p>
              {updates.data.message && <p className="text-warn">{updates.data.message}</p>}
              {updates.data.checked_at && <p>Last checked: {new Date(updates.data.checked_at).toLocaleString()}</p>}
              <p>Private Dev images require GHCR read:packages credentials in the root-owned store. Use an authenticated owner terminal; do not paste the token into this unprivileged desktop or Hermes.</p>
              <pre className="selectable whitespace-pre-wrap rounded-lg bg-black/20 p-3 text-[11px]">su - YOUR_OWNER{ '\n' }sudo haos-owner update login{ '\n' }sudo haos-owner update channel dev --auto-stage</pre>
              <p>Stable channel: <code>sudo haos-owner update channel stable</code> (available only after an official stable image is published).</p>
            </div>
          ) : undefined}>
          <GlassButton size="sm" variant="ghost" onClick={updates.reload}>Refresh status</GlassButton>
          <GlassButton size="sm" onClick={() => openApp('terminal')} aria-label="Open Terminal">
            Open Terminal
          </GlassButton>
        </SettingsRow>
        <SettingsRow
          icon={<IconFileText />}
          label="Open logs"
          description="The last 300 lines from the Hermes backend this shell started."
          keywords="log output debug backend"
          below={showLog ? <LogView lines={log.data ?? []} empty={log.loading ? 'Loading…' : 'No log output yet.'} className="animate-rise" /> : undefined}
        >
          {showLog && (
            <GlassButton size="sm" variant="ghost" onClick={log.reload}>
              Refresh
            </GlassButton>
          )}
          <GlassButton size="sm" onClick={() => setShowLog(o => !o)} aria-label={showLog ? 'Hide logs' : 'Open logs'}>
            {showLog ? 'Hide logs' : 'Open logs'}
          </GlassButton>
        </SettingsRow>
      </SettingsGroup>
    </>
  )
}
