import { describe, expect, it } from 'vitest'
import { localModelConfig, localModelSwitch } from './local-models.ts'

describe('localModelConfig', () => {
  it('points Hermes at Ollama through the custom provider', () => {
    expect(localModelConfig('ollama', 'llama3.2')).toEqual({ provider: 'custom', base_url: 'http://127.0.0.1:11434/v1', default: 'llama3.2', api_key: '', api_mode: '' })
    expect(localModelSwitch('ollama', 'llama3.2')).toBe('custom:llama3.2')
  })

  it('uses the LM Studio provider on its default port', () => {
    expect(localModelConfig('lmstudio', 'qwen3-8b')).toMatchObject({ provider: 'lmstudio', base_url: 'http://127.0.0.1:1234/v1', default: 'qwen3-8b' })
    expect(localModelSwitch('lmstudio', 'qwen3-8b')).toBe('lmstudio:qwen3-8b')
  })
})
