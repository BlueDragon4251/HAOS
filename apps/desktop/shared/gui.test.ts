import { describe, expect, it } from 'vitest'
import { missionDocument, validateGuiAction } from './gui.ts'

const window = '42514251-0000-4000-8000-000000000003'
describe('GUI independent native admission boundary', () => {
  it.each([
    { operation: 'open', html: 'text', url: 'file:///etc/shadow' },
    { operation: 'capture', window: 42 }, { operation: ['capture'], window },
    { operation: 'click', window, x: 1, y: 1 }, { operation: 'click', window, x: true, y: 50 },
    { operation: 'type', window, text: '\n' }, { operation: 'key', window, key: 'Control+V' },
    { operation: 'open', html: 'é'.repeat(20000) }, { operation: 'shell', command: 'sudo' },
    { operation: 'open', html: '<iframe srcdoc="nested"></iframe>' },
    { operation: 'scroll', window, x: 30, y: 60, deltaX: 0, deltaY: 553 },
    { operation: 'scroll', window, x: 30, y: 60, deltaX: true, deltaY: 100 },
    { operation: 'scroll', window, x: 30, y: 60, deltaX: 0, deltaY: 0 },
    { operation: 'read', window, selector: 'owner' }
  ])('denies authority outside the local browser: %j', value => expect(() => validateGuiAction(value)).toThrow())
  it('contains caller markup in an opaque sandbox below the immutable mission banner', () => {
    const html = missionDocument(window, '"></iframe><script>owner()</script>')
    expect(html.match(/<iframe/g)).toHaveLength(1)
    expect(html.match(/<\/iframe>/g)).toHaveLength(1)
    expect(html).toContain('iframe sandbox srcdoc=')
    expect(html).toContain("script-src 'none'")
    expect(html).toContain('&lt;script&gt;')
    expect(() => missionDocument('owner', 'html')).toThrow()
  })
})
