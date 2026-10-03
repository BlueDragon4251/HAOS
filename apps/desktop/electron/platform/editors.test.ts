import { describe, expect, it } from 'vitest'
import { findCodeEditor } from './editors.ts'

const app = (name: string) => ({ name, path: `/Applications/${name}.app` })

describe('findCodeEditor', () => {
  it('picks VS Code, then Cursor, then Zed, whatever order the apps are listed in', () => {
    expect(findCodeEditor([app('Zed'), app('Cursor'), app('Visual Studio Code')]).name).toBe('Visual Studio Code')
    expect(findCodeEditor([app('Safari'), app('Zed'), app('Cursor')]).name).toBe('Cursor')
    expect(findCodeEditor([app('zed')]).path).toBe('/Applications/zed.app')
  })

  it('says which editors it looked for when none is installed', () => {
    expect(() => findCodeEditor([app('Safari')])).toThrow('Visual Studio Code, Cursor, Zed')
  })
})
