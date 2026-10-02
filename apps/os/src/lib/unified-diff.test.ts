import { describe, expect, it } from 'vitest'
import { parseUnifiedDiff } from './unified-diff.ts'

describe('parseUnifiedDiff', () => {
  it('reports added lines in new-file numbering', () => {
    const diff = ['--- a/src/styles.css', '+++ b/src/styles.css', '@@ -1,4 +1,5 @@', ' body {', '-  color: black;', '+  color: hotpink;', '+  margin: 0;', ' }', ''].join('\n')
    expect(parseUnifiedDiff(diff)).toEqual([{ path: 'src/styles.css', created: false, deleted: false, added: [2, 3], removed: 1 }])
  })

  it('handles new files, several files and several hunks', () => {
    const diff = [
      '--- /dev/null',
      '+++ b/index.html',
      '@@ -0,0 +1,2 @@',
      '+<h1>Salon</h1>',
      '+<p>Book now</p>',
      '--- a/app.js',
      '+++ b/app.js',
      '@@ -1,2 +1,2 @@',
      '-let a = 1',
      '+let a = 2',
      ' let b = 1',
      '@@ -10,1 +10,2 @@',
      ' x()',
      '+y()'
    ].join('\n')
    const files = parseUnifiedDiff(diff)
    expect(files[0]).toMatchObject({ path: 'index.html', created: true, added: [1, 2] })
    expect(files[1]).toMatchObject({ path: 'app.js', created: false, added: [1, 11], removed: 1 })
  })

  it("reads Hermes's rendered transcript diff (colours, banner, a/ → b/ headers)", () => {
    const diff = [
      '  ┊ review diff',
      '\u001b[38;2;218;165;32ma//Users/me/site/styles.css → b//Users/me/site/styles.css\u001b[0m',
      '\u001b[38;2;139;134;130m@@ -72,3 +72,3 @@\u001b[0m',
      ' .site-header{',
      '\u001b[31m-  background:white;\u001b[0m',
      '\u001b[32m+  background:pink;\u001b[0m',
      '   position:sticky;',
      'a//Users/me/site/index.html → b//Users/me/site/index.html',
      '@@ -0,0 +1,2 @@',
      '+<h1>Salon</h1>',
      '+<p>Hi</p>'
    ].join('\n')
    expect(parseUnifiedDiff(diff)).toEqual([
      { path: '/Users/me/site/styles.css', created: false, deleted: false, added: [73], removed: 1 },
      { path: '/Users/me/site/index.html', created: true, deleted: false, added: [1, 2], removed: 0 }
    ])
  })

  it('returns nothing for empty input', () => {
    expect(parseUnifiedDiff(null)).toEqual([])
    expect(parseUnifiedDiff('')).toEqual([])
  })
})
