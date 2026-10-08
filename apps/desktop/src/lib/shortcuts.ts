import type { KeyboardEvent as ReactKeyboardEvent } from 'react'

/*
 * Keyboard shortcuts written once for both systems: `mod` is ⌘ on the Mac and Ctrl elsewhere, so
 * `mod+shift+s` is ⇧⌘S on one and Ctrl+Shift+S on the other.
 */

/** ⌘ is the command key on the Mac; Ctrl takes its place elsewhere. */
export const isMac = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform)

/** How a shortcut reads on this system: ⇧⌘S on the Mac, Ctrl+Shift+S elsewhere. */
export function keysLabel(keys: string): string {
  const parts = keys.split('+')
  const key = parts.pop()!
  const named: Record<string, string> = isMac ? { '=': '+', '-': '−', backspace: '⌫', delete: '⌦' } : { '=': '+', '-': '−', backspace: 'Backspace', delete: 'Delete' }
  const shown = named[key] ?? key.toUpperCase()

  if (isMac) {
    const symbols: Record<string, string> = { mod: '⌘', shift: '⇧', alt: '⌥', ctrl: '⌃' }
    const order = ['ctrl', 'alt', 'shift', 'mod']

    return `${order.filter((mod) => parts.includes(mod)).map((mod) => symbols[mod]).join('')}${shown}`
  }

  const words: Record<string, string> = { mod: 'Ctrl', shift: 'Shift', alt: 'Alt', ctrl: 'Ctrl' }

  return [...parts.map((mod) => words[mod]), shown].join('+')
}

/** Does a key press match a shortcut? */
export function matches(event: KeyboardEvent | ReactKeyboardEvent, keys: string): boolean {
  const parts = keys.split('+')
  const key = parts.pop()!
  const mod = isMac ? event.metaKey : event.ctrlKey

  if (parts.includes('mod') !== mod || parts.includes('shift') !== event.shiftKey || parts.includes('alt') !== event.altKey) {
    return false
  }

  if (isMac && event.ctrlKey && !parts.includes('ctrl')) {
    return false
  }

  // Shifted and option layers change event.key, so letters and digits match on the physical key.
  const code = event.code
  const pressed = /^Key[A-Z]$/.test(code) ? code.slice(3).toLowerCase() : /^Digit\d$/.test(code) ? code.slice(5) : event.key.toLowerCase()
  const aliases: Record<string, string[]> = { '=': ['=', '+'], '-': ['-', '_'], ']': [']', '}'], '[': ['[', '{'], ';': [';', ':'] }

  return (
    (aliases[key] ?? [key]).includes(pressed) ||
    (key === '=' && code === 'Equal') ||
    (key === '-' && code === 'Minus') ||
    (key === ']' && code === 'BracketRight') ||
    (key === '[' && code === 'BracketLeft') ||
    (key === ';' && code === 'Semicolon')
  )
}
