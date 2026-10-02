import { describe, expect, it } from 'vitest'
import { buildBrief, projectSlug, uniqueName } from './build-brief.ts'

describe('projectSlug', () => {
  it('keeps the meaningful words', () => {
    expect(projectSlug('a website for a hair salon')).toBe('website-hair-salon')
    expect(projectSlug('an app that tracks my runs')).toBe('app-tracks-runs')
    expect(projectSlug('Café São Paulo!')).toBe('cafe-sao-paulo')
    expect(projectSlug('a the for')).toBe('project')
  })
})

describe('uniqueName', () => {
  it('adds a number when the folder exists', () => {
    expect(uniqueName('salon', new Set())).toBe('salon')
    expect(uniqueName('salon', new Set(['salon', 'salon-2']))).toBe('salon-3')
  })
})

describe('buildBrief', () => {
  it('names the goal, the folder and how to show the work', () => {
    const brief = buildBrief('a website for a hair salon', '/Users/me/Projects/website-hair-salon')
    expect(brief).toContain('Build this: a website for a hair salon')
    expect(brief).toContain('/Users/me/Projects/website-hair-salon')
    expect(brief).toContain('write_file')
    expect(brief).toContain('studio.preview')
  })
})
