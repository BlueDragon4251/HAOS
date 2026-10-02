import { describe, expect, it } from 'vitest'
import { STT_VOCABULARY, sttTuningPatch } from './stt-tuning.ts'

describe('sttTuningPatch', () => {
  it('upgrades the default local model and adds the vocabulary', () => {
    expect(sttTuningPatch({})).toEqual({ stt: { local: { model: 'small.en', initial_prompt: STT_VOCABULARY } } })
    expect(sttTuningPatch({ stt: { provider: 'local', local: { model: 'base', initial_prompt: '' } } })).toEqual({ stt: { local: { model: 'small.en', initial_prompt: STT_VOCABULARY } } })
  })

  it('keeps choices the user already made', () => {
    expect(sttTuningPatch({ stt: { local: { model: 'medium.en', initial_prompt: 'my words' } } })).toBeNull()
    expect(sttTuningPatch({ stt: { local: { model: 'medium.en' } } })).toEqual({ stt: { local: { initial_prompt: STT_VOCABULARY } } })
    expect(sttTuningPatch({ stt: { provider: 'openai' } })).toBeNull()
  })
})
