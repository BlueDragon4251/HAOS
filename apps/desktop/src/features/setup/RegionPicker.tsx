import { IconKeyboard, IconLanguage } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { HAOS_KEYBOARDS, HAOS_LANGUAGES, type HaosRegion, DEFAULT_HAOS_REGION } from '../../../shared/region.ts'
import { GlassButton } from '../../components/ui/glass.tsx'
import { Spinner } from '../../components/ui/primitives.tsx'
import { markSaved, SettingsGroup, SettingsRow } from '../settings/sections/shared.tsx'

/** Bilingual bootstrap, before the user has selected a locale. */
export function RegionPicker({ onSaved }: { onSaved?: () => void }) {
  const [region, setRegion] = useState<HaosRegion>(DEFAULT_HAOS_REGION)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    void window.heraldOS.setup.region().then(value => {
      if (alive) setRegion(value)
    }).catch(() => undefined)
    return () => { alive = false }
  }, [])

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await window.heraldOS.setup.setRegion(region)
      if (!result.ok) {
        setError(result.error || 'Regional settings could not be saved.')
        return
      }
      setSaved('Gespeichert / Saved · Das Tastaturlayout ist aktiv.')
      markSaved()
      onSaved?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3 text-[12.5px]">
      <label className="flex flex-col gap-1.5 text-fg-2">
        Sprache / Language
        <select className="glass-input h-10 w-full rounded-lg px-3 text-fg"
          aria-label="Sprache / Language"
          value={region.language}
          onChange={e => setRegion(previous => ({ ...previous, language: e.target.value as HaosRegion['language'] }))}>
          {HAOS_LANGUAGES.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1.5 text-fg-2">
        Tastaturlayout / Keyboard layout
        <select className="glass-input h-10 w-full rounded-lg px-3 text-fg"
          aria-label="Tastaturlayout / Keyboard layout"
          value={region.keyboard}
          onChange={e => setRegion(previous => ({ ...previous, keyboard: e.target.value as HaosRegion['keyboard'] }))}>
          {HAOS_KEYBOARDS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </label>
      <p className="text-fg-3">Die Tastatur gilt sofort und auch nach Neustart. Die Sitzungssprache wird ab der nächsten Anmeldung übernommen. Die noch englischen HAOS-Oberflächentexte benötigen eigene Übersetzungen.</p>
      <div className="flex items-center justify-between gap-3">
        <span className="text-[12px] text-danger" role="alert">{error}</span>
        {saved && !error && <span className="text-ok">{saved}</span>}
        <GlassButton size="sm" variant="primary" onClick={() => void save()} disabled={busy}>
          {busy && <Spinner />} {onSaved ? 'Übernehmen / Continue' : 'Speichern / Save'}
        </GlassButton>
      </div>
    </div>
  )
}

/** The same regional chooser stays accessible after first boot. */
export function RegionSettings() {
  return (
    <SettingsGroup title="Language & keyboard">
      <SettingsRow icon={<IconLanguage />} label="Region and keyboard layout"
        description="Desktop language, physical keyboard, QWERTZ/QWERTY. Not the Herald/Omarchy hotkey preset."
        keywords="language locale German Deutsch Österreich Austria keyboard Tastaturlayout QWERTZ">
        <IconKeyboard size={17} />
      </SettingsRow>
      <div className="settings-item px-4 pb-4">
        <RegionPicker />
      </div>
    </SettingsGroup>
  )
}
