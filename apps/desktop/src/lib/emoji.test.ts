import { describe, expect, it } from 'vitest'
import { EMOJI, EMOJI_GROUPS, searchEmoji } from './emoji.ts'

describe('emoji catalogue', () => {
  it('parses every row into a character, name and group', () => {
    expect(EMOJI.length).toBeGreaterThan(300)
    expect(EMOJI.every(emoji => emoji.char && emoji.name && emoji.group)).toBe(true)
    expect(EMOJI_GROUPS[0]).toBe('Smileys')
    expect(EMOJI_GROUPS).toContain('Symbols')
  })

  it('has no duplicate characters', () => {
    const chars = EMOJI.map(emoji => emoji.char)
    expect(new Set(chars).size).toBe(chars.length)
  })
})

describe('searchEmoji', () => {
  it('returns the start of the catalogue for an empty query', () => {
    expect(searchEmoji('', 3).map(emoji => emoji.char)).toEqual(['😀', '😃', '😄'])
  })

  it('ranks a name prefix above a keyword match', () => {
    const [first] = searchEmoji('rocket')
    expect(first?.char).toBe('🚀')
    expect(searchEmoji('thumbs')[0]?.char).toBe('👍')
  })

  it('finds by keyword and needs every word to match', () => {
    expect(searchEmoji('tada').map(emoji => emoji.char)).toContain('🎉')
    expect(searchEmoji('heart broken').map(emoji => emoji.char)).toEqual(['💔'])
    expect(searchEmoji('zzzzqqq')).toEqual([])
  })

  it('caps the number of results', () => {
    expect(searchEmoji('heart', 5)).toHaveLength(5)
  })
})
