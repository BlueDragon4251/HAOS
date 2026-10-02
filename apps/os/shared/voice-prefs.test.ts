import { describe, expect, it } from 'vitest'
import { normalizeVoicePrefs, VOICE_DEFAULTS } from './voice-prefs.ts'

describe('normalizeVoicePrefs', () => {
  it('fills defaults for missing or malformed values', () => {
    expect(normalizeVoicePrefs(undefined)).toEqual(VOICE_DEFAULTS)
    expect(normalizeVoicePrefs('junk')).toEqual(VOICE_DEFAULTS)
  })

  it('keeps valid values and clamps numbers', () => {
    const prefs = normalizeVoicePrefs({ enabled: true, engine: 'live', liveIdleSeconds: 5, liveDailyCapMinutes: 99_999, followUpSeconds: 12, liveUsage: { day: '2026-09-22', seconds: 120 } })
    expect(prefs.enabled).toBe(true)
    expect(prefs.engine).toBe('live')
    expect(prefs.liveIdleSeconds).toBe(10)
    expect(prefs.liveDailyCapMinutes).toBe(24 * 60)
    expect(prefs.followUpSeconds).toBe(12)
    expect(prefs.liveUsage).toEqual({ day: '2026-09-22', seconds: 120 })
  })

  it('rejects unknown engines', () => {
    expect(normalizeVoicePrefs({ engine: 'realtime' }).engine).toBe('chained')
  })
})
