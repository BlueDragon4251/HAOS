import { describe, expect, it } from 'vitest'
import type { RecentFile } from '../../shared/ipc.ts'
import { normaliseFileQuery, rankFiles } from './find.ts'

const file = (path: string, lastUsedAt = 0): RecentFile => {
  const name = path.split('/').pop() ?? path
  return { path, name, extension: name.split('.').pop() ?? '', size: 1, modifiedAt: 0, lastUsedAt, kind: 'file' }
}

describe('normaliseFileQuery', () => {
  it('turns spoken names into file names', () => {
    expect(normaliseFileQuery('Hello dot PDF')).toBe('hello.pdf')
    expect(normaliseFileQuery('"report .docx"')).toBe('report.docx')
  })
})

describe('rankFiles', () => {
  it('prefers exact names, then user folders, then recent use', () => {
    const files = [
      file('/Users/me/Library/Caches/hello.pdf', 9),
      file('/Users/me/Documents/hello-world.pdf', 5),
      file('/Users/me/Downloads/hello.pdf', 1),
      file('/Users/me/Downloads/other.txt', 9)
    ]
    expect(rankFiles('hello dot pdf', files, 5).map(f => f.path)).toEqual(['/Users/me/Downloads/hello.pdf', '/Users/me/Library/Caches/hello.pdf', '/Users/me/Documents/hello-world.pdf'])
    expect(rankFiles('hello', files, 1)[0].path).toBe('/Users/me/Downloads/hello.pdf')
  })
})
