import { describe, expect, it } from 'vitest'
import { isExcluded } from './continuity.ts'

const HOME = '/Users/sam'

describe('isExcluded', () => {
  it('hides everything inside an excluded folder, written absolute or with ~', () => {
    expect(isExcluded('/Users/sam/Clients/Acme/deck.key', ['/Users/sam/Clients'], HOME)).toBe(true)
    expect(isExcluded('/Users/sam/Clients/Acme/deck.key', ['~/Clients/'], HOME)).toBe(true)
    expect(isExcluded('/Users/sam/Clients', ['~/Clients'], HOME)).toBe(true)
  })

  it('does not hide siblings that only share a prefix', () => {
    expect(isExcluded('/Users/sam/ClientsArchive/a.txt', ['~/Clients'], HOME)).toBe(false)
  })

  it('hides titles that mention an excluded folder by name', () => {
    expect(isExcluded('Draft the Acme proposal', ['~/Work/Acme'], HOME)).toBe(true)
    expect(isExcluded('Fix the build', ['~/src'], HOME)).toBe(false)
  })

  it('matches words anywhere, ignoring case and separators', () => {
    expect(isExcluded('/Users/sam/Downloads/sam-project-falcon-2x.pdf', ['Project Falcon'], HOME)).toBe(true)
    expect(isExcluded('Quarterly ACME_review.pptx', ['acme review'], HOME)).toBe(true)
    expect(isExcluded('Microsoft Teams', ['teams'], HOME)).toBe(true)
  })

  it('ignores blank entries and empty text', () => {
    expect(isExcluded('/Users/sam/notes.md', ['', '   '], HOME)).toBe(false)
    expect(isExcluded('', ['notes'], HOME)).toBe(false)
  })
})
