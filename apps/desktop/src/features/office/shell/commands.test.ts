import { describe, expect, it, vi } from 'vitest'
import { isMac } from '../../../lib/shortcuts.ts'
import type { OfficeSession } from '../session.ts'
import { officeMenus, runShortcut } from './commands.ts'

/** The parts of a session the shared menus use. */
function fakeSession(active: object | null) {
  return { active: () => active, create: vi.fn(), openPicked: vi.fn(async () => {}), save: vi.fn(async () => true), exportPdf: vi.fn(async () => null), $dialog: { set: vi.fn() } }
}

const press = (key: string, shift = false) => ({ key, code: `Key${key.toUpperCase()}`, metaKey: isMac, ctrlKey: !isMac, shiftKey: shift, altKey: false }) as KeyboardEvent

describe('officeMenus and runShortcut', () => {
  it('runs the file shortcuts against the session', () => {
    const session = fakeSession({ key: 'docs-1', notes: [] })
    const menus = officeMenus({ session: session as unknown as OfficeSession<unknown>, canSave: true })

    expect(runShortcut(press('n'), menus)).toBe(true)
    expect(session.create).toHaveBeenCalledOnce()
    expect(runShortcut(press('s'), menus)).toBe(true)
    expect(session.save).toHaveBeenCalledOnce()
    expect(runShortcut(press('s', true), menus)).toBe(true)
    expect(session.save).toHaveBeenLastCalledWith(expect.anything(), { as: true })
    expect(runShortcut(press('p'), menus)).toBe(true)
    expect(session.exportPdf).toHaveBeenCalledOnce()
  })

  it('leaves alone what does not apply: saving without a format, opening without one, closing with nothing open', () => {
    const session = fakeSession(null)
    const menus = officeMenus({ session: session as unknown as OfficeSession<unknown>, canOpen: false, canSave: false })

    expect(runShortcut(press('s'), menus)).toBe(false)
    expect(runShortcut(press('o'), menus)).toBe(false)
    expect(runShortcut(press('w'), menus)).toBe(false)
    expect(session.save).not.toHaveBeenCalled()
    expect(session.openPicked).not.toHaveBeenCalled()
  })

  it('adds the app’s own menus after File and Edit', () => {
    const menus = officeMenus({ session: fakeSession(null) as unknown as OfficeSession<unknown>, canSave: true, menus: [{ id: 'slide', label: 'Slide', items: [] }] })

    expect(menus.map((menu) => menu.label)).toEqual(['File', 'Edit', 'Slide'])
  })
})
