import { describe, expect, it } from 'vitest'
import { clockText, MENU_BAR_ITEMS, moveMenuBarItem, normalizeMenuBar, resolveMenuBarItem, visibleMenuBarItems } from './menu-bar.ts'

describe('normalizeMenuBar', () => {
  it('gives the default layout for nothing stored', () => {
    const layout = normalizeMenuBar(undefined)
    expect(layout.order).toEqual([...MENU_BAR_ITEMS])
    expect(layout.hidden).toEqual([])
    expect(layout.clock).toEqual({ hours: 'system', seconds: false, date: 'short' })
  })

  it('drops unknown and repeated items and puts missing ones beside their neighbours', () => {
    const layout = normalizeMenuBar({ order: ['clock', 'wifi', 'clock', 'teleporter', 'search'] })
    expect(layout.order[0]).toBe('clock')
    expect(new Set(layout.order).size).toBe(MENU_BAR_ITEMS.length)
    // Bluetooth follows Wi-Fi by default, so it comes back right after it.
    expect(layout.order.indexOf('bluetooth')).toBe(layout.order.indexOf('wifi') + 1)
  })

  it('never hides the status lights, and leaves plan usage to its own switch', () => {
    const layout = normalizeMenuBar({ hidden: ['indicators', 'usage', 'battery', 'battery', 'nope'] })
    expect(layout.hidden).toEqual(['battery'])
    expect(visibleMenuBarItems(layout)).toContain('indicators')
    expect(visibleMenuBarItems(layout)).not.toContain('battery')
  })

  it('keeps only known clock settings', () => {
    expect(normalizeMenuBar({ clock: { hours: '24', seconds: true, date: 'none' } }).clock).toEqual({ hours: '24', seconds: true, date: 'none' })
    expect(normalizeMenuBar({ clock: { hours: 13, seconds: 'yes', date: 'medium' } }).clock).toEqual({ hours: 'system', seconds: false, date: 'short' })
  })
})

describe('moveMenuBarItem', () => {
  it('moves an item and clamps the position', () => {
    const order = normalizeMenuBar(undefined).order
    expect(moveMenuBarItem(order, 'clock', 0)[0]).toBe('clock')
    expect(moveMenuBarItem(order, 'search', 99).at(-1)).toBe('search')
    expect(moveMenuBarItem(order, 'search', -5)[0]).toBe('search')
    expect(moveMenuBarItem(order, 'wifi', 3)).toHaveLength(order.length)
  })
})

describe('resolveMenuBarItem', () => {
  it('accepts ids, labels and everyday words', () => {
    expect(resolveMenuBarItem('battery')).toBe('battery')
    expect(resolveMenuBarItem('Wi-Fi')).toBe('wifi')
    expect(resolveMenuBarItem('volume')).toBe('sound')
    expect(resolveMenuBarItem('Plan usage')).toBe('usage')
    expect(resolveMenuBarItem('dock')).toBeNull()
  })
})

describe('clockText', () => {
  const at = new Date(2026, 9, 6, 20, 5, 9)

  it('follows the hour cycle, seconds and date settings', () => {
    expect(clockText(at, { hours: '24', seconds: false, date: 'none' }, 'en-US')).toEqual({ date: null, time: '20:05' })
    // Some ICU versions put a narrow no-break space before "PM".
    expect(clockText(at, { hours: '12', seconds: true, date: 'none' }, 'en-US').time.replace(/\s/g, ' ')).toBe('8:05:09 PM')
    expect(clockText(at, { hours: '24', seconds: false, date: 'short' }, 'en-US').date).toBe('Tue, Oct 6')
    expect(clockText(at, { hours: '24', seconds: false, date: 'long' }, 'en-US').date).toBe('Tuesday, October 6')
  })
})
