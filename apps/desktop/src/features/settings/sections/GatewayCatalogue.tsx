import { useMemo, useState } from 'react'
import { IconBrandDiscord, IconBrandTelegram, IconPlugConnected, IconSearch } from '@tabler/icons-react'
import { GlassCard } from '../../../components/ui/glass.tsx'

/** Pinned upstream Hermes f97608f plugin-platform inventory.
 * "Available in Hermes" does NOT authorize a platform through HAOS's controller.
 */
export const GATEWAYS = [
  'a2a', 'buzz', 'dingtalk', 'discord', 'email', 'feishu',
  'googlechat', 'homeassistant', 'irc', 'line', 'mattermost', 'matrix',
  'ntfy', 'photon', 'raft', 'simplex', 'slack', 'sms', 'teams',
  'telegram', 'wecom', 'whatsapp'
] as const

export const HAOS_APPROVED_GATEWAYS = new Set<string>(['telegram', 'discord', 'slack', 'mattermost'])

const names: Record<string, string> = {
  a2a: 'Agent-to-Agent', buzz: 'Buzz', dingtalk: 'DingTalk',
  discord: 'Discord', email: 'Email (IMAP / SMTP)', feishu: 'Feishu',
  googlechat: 'Google Chat', homeassistant: 'Home Assistant',
  irc: 'IRC', line: 'LINE', mattermost: 'Mattermost',
  matrix: 'Matrix', ntfy: 'ntfy', photon: 'Photon',
  raft: 'Raft', simplex: 'SimpleX', slack: 'Slack',
  sms: 'SMS', teams: 'Microsoft Teams', telegram: 'Telegram',
  wecom: 'WeCom', whatsapp: 'WhatsApp'
}

export function GatewayCatalogue() {
  const [search, setSearch] = useState('')
  const filtered = useMemo(() => GATEWAYS.filter(p => names[p].toLowerCase().includes(search.toLowerCase().trim())), [search])
  return (
    <GlassCard className="flex flex-col gap-3 px-4 py-4">
      <div className="flex items-center gap-2">
        <IconPlugConnected size={18} className="text-accent" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-[13px]">Hermes Gateways</div>
          <div className="text-[11.5px] text-fg-3">22 Adapter im eingebundenen Hermes-Quellstand</div>
        </div>
      </div>
      <div className="text-[12px] text-fg-2">
        HAOS beschränkt derzeit den autorisierten Nachrichteneingang auf Telegram, Discord, Slack und Mattermost.
        Alle anderen Adapter werden erst aktiviert, wenn Zugangsdaten, Absenderbindung und
        Zustellung nachweislich im HAOS-Sicherheitsmodell funktionieren.
      </div>
      <label className="flex items-center gap-2 rounded-lg border border-line bg-white/5 px-3 py-2">
        <IconSearch size={15} className="text-fg-3" />
        <input value={search} onChange={e => setSearch(e.target.value)}
          className="w-full bg-transparent text-[12.5px] outline-none" placeholder="Gateways durchsuchen"
          aria-label="Hermes Gateways durchsuchen" />
      </label>
      <div className="grid max-h-[330px] grid-cols-1 gap-2 overflow-auto sm:grid-cols-2">
        {filtered.map(platform => {
          const admitted = HAOS_APPROVED_GATEWAYS.has(platform)
          return (
            <div key={platform} className="flex items-center gap-2 rounded-xl border border-line px-3 py-2.5">
              {platform === 'telegram'
                ? <IconBrandTelegram size={18} className="shrink-0 text-fg-2" />
                : platform === 'discord'
                  ? <IconBrandDiscord size={18} className="shrink-0 text-fg-2" />
                  : <IconPlugConnected size={18} className="shrink-0 text-fg-3" />}
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12px] font-semibold text-fg">{names[platform]}</div>
                <div className="text-[10px] text-fg-3">{admitted ? 'HAOS-Adapter vorhanden' : 'Upstream; HAOS noch nicht freigegeben'}</div>
              </div>
            </div>
          )
        })}
      </div>
      <p className="text-[11px] text-fg-3">Diese Anzeige bestätigt keine Live-Verbindung. Einrichtung und genaue Absenderfreigaben erfolgen in der grafischen HAOS-Owner-Konsole. Weitere Plattformen und Medienpfade befinden sich in Entwicklung.</p>
    </GlassCard>
  )
}
