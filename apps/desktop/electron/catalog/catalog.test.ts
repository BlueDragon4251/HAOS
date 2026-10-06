import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { entryView, findEntry, macGroups, parseCliListing, pickMacMethod, readCatalog, terminalBin } from './catalog.ts'

const CATALOG = fileURLToPath(new URL('../../../../linux/catalog', import.meta.url))
const groups = readCatalog(['/nonexistent', CATALOG])

describe('readCatalog', () => {
  it('reads the first folder that has groups, in order', () => {
    expect(groups.map(group => group.id)).toEqual(['ai', 'developer', 'editors', 'terminals', 'gaming', 'windows', 'media', 'services', 'webapps'])
    expect(readCatalog(['/nonexistent'])).toEqual([])
  })
})

describe('terminalBin', () => {
  it('only runs the coding agents', () => {
    expect(terminalBin(groups, 'claude-code')).toBe('claude')
    expect(terminalBin(groups, 'codex')).toBe('codex')
    expect(terminalBin(groups, 'steam')).toBeNull()
    expect(terminalBin(groups, 'nope; rm -rf ~')).toBeNull()
  })
})

describe('macOS', () => {
  const mac = macGroups(groups)

  it('keeps only what installs on a Mac', () => {
    expect(mac.map(group => group.id)).toEqual(['ai', 'services'])
    expect(mac[0]?.entries.map(entry => entry.id)).toEqual(['claude-code', 'codex', 'opencode', 'gemini-cli', 'copilot-cli', 'ollama', 'lm-studio'])
    expect(mac[1]?.entries.map(entry => entry.id)).toEqual(['1password'])
  })

  it('picks npm, Homebrew or the download page by what the Mac has', () => {
    const ollama = findEntry(groups, 'ollama')?.entry

    if (!ollama) {
      throw new Error('ollama missing from the catalog')
    }

    expect(pickMacMethod(ollama, { npm: true, brew: true }).method?.kind).toBe('brew')
    expect(pickMacMethod(ollama, { npm: true, brew: false }).method?.kind).toBe('link')
    const claude = findEntry(groups, 'claude-code')?.entry

    if (!claude) {
      throw new Error('claude-code missing from the catalog')
    }

    expect(pickMacMethod(claude, { npm: false, brew: true })).toEqual({ method: null, reason: 'needs Node.js (from nodejs.org or Homebrew)' })
  })

  it('describes an entry for the shell', () => {
    const found = findEntry(groups, 'lm-studio')

    if (!found) {
      throw new Error('lm-studio missing from the catalog')
    }

    const view = entryView(found.group, found.entry, { installed: false, ...pickMacMethod(found.entry, { npm: true, brew: false }) })
    expect(view).toMatchObject({ id: 'lm-studio', group: 'ai', available: true, method: 'link', hermes: 'lmstudio', url: 'https://lmstudio.ai/download' })
    expect(view.reason).toBeUndefined()
  })
})

describe('parseCliListing', () => {
  it('reads herald-os catalog list --json', () => {
    const stdout = JSON.stringify({ machine: { arch: 'x86_64' }, groups: [{ id: 'ai', label: 'AI', entries: [{ id: 'codex', label: 'Codex', installed: true }] }] })
    expect(parseCliListing(stdout)).toEqual([{ id: 'ai', label: 'AI', description: '', entries: [{ id: 'codex', label: 'Codex', installed: true }] }])
  })
})
