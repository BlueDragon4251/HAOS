import { describe, expect, it } from 'vitest'
import { buildEntries, ENTRY_DELIMITER, type MemoryFile, parse } from '../memory/memory-store.ts'
import { memorySummary } from './memory-summary.ts'

const MEMORY_MD = [
  'Sam prefers short answers, with the command first and the explanation after.',
  '**Herald OS**: the desktop shell lives in ~/Projects/herald and ships from main (2026-09-30).',
  'Deploys go out on Fridays only after the staging check passes.',
  'Sam reports to Priya on the platform team.'
].join(ENTRY_DELIMITER)
const USER_MD = ['Timezone: Australia/Sydney.', 'Writes in British English.'].join(ENTRY_DELIMITER)

function read(files: Partial<Record<MemoryFile, string>>) {
  const entries = Object.entries(files).flatMap(([file, text]) =>
    buildEntries({ file: file as MemoryFile, path: `/home/sam/.hermes/memories/${file}`, exists: true, modifiedAt: 0, truncated: false, texts: parse(text ?? '') })
  )

  return { entries, loaded: true, error: null }
}

describe('memorySummary', () => {
  it('counts the entries in both files, not the bytes in MEMORY.md', () => {
    expect(MEMORY_MD.length).toBeGreaterThan(200)
    expect(memorySummary(read({ 'MEMORY.md': MEMORY_MD }), false)).toEqual({ label: 'Memory on', detail: '4 entries remembered' })
    expect(memorySummary(read({ 'MEMORY.md': MEMORY_MD, 'USER.md': USER_MD }), false)?.detail).toBe('6 entries remembered')
    expect(memorySummary(read({ 'USER.md': 'Timezone: Australia/Sydney.' }), false)?.detail).toBe('1 entry remembered')
  })

  it('says paused only when the memory toolset is off, and keeps counting what is still used', () => {
    expect(memorySummary(read({ 'MEMORY.md': '' }), false)).toEqual({ label: 'Memory on', detail: 'Nothing remembered yet' })
    expect(memorySummary(read({ 'MEMORY.md': MEMORY_MD }), true)).toEqual({ label: 'Memory paused', detail: '4 entries still in use' })
    expect(memorySummary(read({}), true)).toEqual({ label: 'Memory paused', detail: 'Nothing remembered yet' })
  })

  it('waits for the first read, and says when it failed', () => {
    expect(memorySummary({ entries: [], loaded: false, error: null }, false)).toBeNull()
    expect(memorySummary({ entries: [], loaded: true, error: 'EACCES: permission denied' }, false)).toEqual({ label: 'Memory on', detail: 'Could not read memory' })
  })
})
