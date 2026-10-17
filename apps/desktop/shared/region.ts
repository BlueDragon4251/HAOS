/** Explicit regional preferences supported in HAOS (no untrusted locale strings). */
export const HAOS_LANGUAGES = [
  { id: 'de_AT.UTF-8', label: 'Deutsch (Österreich)' },
  { id: 'de_DE.UTF-8', label: 'Deutsch (Deutschland)' },
  { id: 'en_US.UTF-8', label: 'English (United States)' },
  { id: 'en_GB.UTF-8', label: 'English (United Kingdom)' },
  { id: 'fr_FR.UTF-8', label: 'Français (France)' }
] as const

export const HAOS_KEYBOARDS = [
  { id: 'at', label: 'Deutsch (Österreich) · QWERTZ' },
  { id: 'de', label: 'Deutsch (Deutschland) · QWERTZ' },
  { id: 'us', label: 'English (US) · QWERTY' },
  { id: 'gb', label: 'English (UK) · QWERTY' },
  { id: 'fr', label: 'Français (AZERTY)' },
  { id: 'ch', label: 'Schweiz / Suisse' }
] as const

export type HaosLanguage = (typeof HAOS_LANGUAGES)[number]['id']
export type HaosKeyboard = (typeof HAOS_KEYBOARDS)[number]['id']
export interface HaosRegion {
  language: HaosLanguage
  keyboard: HaosKeyboard
}

export const DEFAULT_HAOS_REGION: HaosRegion = { language: 'en_US.UTF-8', keyboard: 'us' }

export function validHaosRegion(value: unknown): value is HaosRegion {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const record = value as Record<string, unknown>
  return Object.keys(record).length === 2
    && HAOS_LANGUAGES.some(option => option.id === record.language)
    && HAOS_KEYBOARDS.some(option => option.id === record.keyboard)
}
