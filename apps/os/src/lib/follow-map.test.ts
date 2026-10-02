import { describe, expect, it } from 'vitest'

// `followCommandFor` is pure but lives in the store module (DOM at import); mirror its table here.
import { followCommandFor } from '../store/follow-map.ts'

describe('followCommandFor', () => {
  it('shows the memory page after memory writes, filtered to the new text', () => {
    expect(followCommandFor({ name: 'memory', args: { action: 'add', content: 'User prefers short answers' } })).toEqual({ command: 'memory.show', args: { query: 'User prefers short answers' } })
    expect(followCommandFor({ name: 'memory', args: { action: 'remove', content: 'x' } })).toEqual({ command: 'memory.show', args: {} })
    expect(followCommandFor({ name: 'memory', args: { action: 'search', query: 'x' } })).toBeNull()
  })

  it('shows the automation after cron changes', () => {
    expect(followCommandFor({ name: 'cronjob', args: { action: 'create', name: 'Daily digest' } })).toEqual({ command: 'automation.show', args: { name: 'Daily digest' } })
    expect(followCommandFor({ name: 'cronjob', args: { action: 'remove', name: 'x' } })).toEqual({ command: 'automation.list', args: {} })
  })

  it('opens the folder of a written file and ignores other tools', () => {
    expect(followCommandFor({ name: 'write_file', args: { path: '/Users/me/notes/todo.md' } })).toEqual({ command: 'files.open', args: { place: '/Users/me/notes' } })
    expect(followCommandFor({ name: 'terminal', args: { command: 'ls' } })).toBeNull()
  })
})
