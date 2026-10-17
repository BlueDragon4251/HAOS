import { useState } from 'react'
import { GlassButton } from '../../../components/ui/glass.tsx'

type Kind = 'openai-codex' | 'openai' | 'openrouter' | 'local'
const OPTIONS: { id: Kind; label: string }[] = [
  { id: 'openai-codex', label: 'OpenAI Codex (account login)' },
  { id: 'openai', label: 'OpenAI API key' },
  { id: 'openrouter', label: 'OpenRouter API key' },
  { id: 'local', label: 'Local OpenAI-compatible server' }
]

/** Builds instructions only. The HAOS observer cannot write owner credentials. */
export function OwnerProviderSetup() {
  const [kind, setKind] = useState<Kind>('openai-codex')
  const [model, setModel] = useState('')
  const [endpoint, setEndpoint] = useState('http://127.0.0.1:11434/v1')
  const validModel = /^[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}$/.test(model)
  const validEndpoint = /^http:\/\/127\.0\.0\.1:(?:[0-9]{4,5})\/v1$/.test(endpoint)
  const ready = validModel && (kind !== 'local' || validEndpoint)
  const args = kind === 'local' ? ` --endpoint ${endpoint}` : ''
  const instructions = [
    'su - YOUR_OWNER',
    'sudo haos-owner stop',
    ...(kind === 'openai-codex' ? ['sudo haos-owner provider login-codex'] : []),
    ...(ready ? [`sudo haos-owner provider configure ${kind} --model ${model}${args}`] : []),
    'sudo haos-owner start'
  ].join('\n')

  return (
    <div className="space-y-3 rounded-xl border border-line p-3 text-[12px]">
      <div className="font-semibold text-fg">Hermes model provider (owner-controlled)</div>
      <label className="flex flex-col gap-1 text-fg-2">
        Provider
        <select className="glass-input rounded-lg p-2 text-fg" value={kind} onChange={event => setKind(event.target.value as Kind)}>
          {OPTIONS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-fg-2">
        Model ID (must be supported by your provider)
        <input className="glass-input rounded-lg p-2 text-fg" value={model} onChange={event => setModel(event.target.value)} placeholder="e.g. gpt-5.4" />
      </label>
      {kind === 'local' && <label className="flex flex-col gap-1 text-fg-2">
        Local API endpoint
        <input className="glass-input rounded-lg p-2 text-fg" value={endpoint} onChange={event => setEndpoint(event.target.value)} />
      </label>}
      <p className="text-fg-3">The configuration is applied only after owner authentication. A GitHub update token is not a Hermes model/API token.</p>
      {ready ? (
        <>
          <pre className="selectable whitespace-pre-wrap rounded-lg bg-black/20 p-2 text-[11px]">{instructions}</pre>
          <GlassButton size="sm" variant="ghost" onClick={() => void navigator.clipboard.writeText(instructions)}>Copy owner commands</GlassButton>
        </>
      ) : <p className="text-fg-3">Enter a valid model ID to generate the owner commands.</p>}
    </div>
  )
}
