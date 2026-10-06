import { describe, expect, it, vi } from 'vitest'

vi.mock('electron', () => ({ ipcMain: { handle: vi.fn() } }))

const { passwdReply } = await import('./setup.ts')

describe('passwdReply', () => {
  it('answers the current password (empty on a new account) and the new one twice', () => {
    expect(passwdReply('Changing password for user hermes.\r\nCurrent password: ', 'hunter22!', '')).toBe('\r')
    expect(passwdReply('New password: ', 'hunter22!', '')).toBe('hunter22!\r')
    expect(passwdReply('Retype new password: ', 'hunter22!', '')).toBe('hunter22!\r')
  })

  it('knows the older prompts', () => {
    expect(passwdReply('(current) UNIX password: ', 'x', 'old')).toBe('old\r')
  })

  it('waits while passwd is still talking', () => {
    expect(passwdReply('Changing password for user hermes.\r\n', 'x', '')).toBeNull()
    expect(passwdReply('passwd: all authentication tokens updated successfully.\r\n', 'x', '')).toBeNull()
  })
})
