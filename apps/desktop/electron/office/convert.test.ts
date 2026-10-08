import { describe, expect, it } from 'vitest'
import { convertArgs, convertWithLibreOffice, sofficeCandidates } from './convert.ts'

describe('sofficeCandidates', () => {
  it('tries the app bundle on the Mac before PATH', () => {
    const list = sofficeCandidates('darwin', { PATH: '/opt/homebrew/bin:/usr/bin' }, '/Users/me')

    expect(list[0]).toBe('/Applications/LibreOffice.app/Contents/MacOS/soffice')
    expect(list[1]).toBe('/Users/me/Applications/LibreOffice.app/Contents/MacOS/soffice')
    expect(list).toContain('/opt/homebrew/bin/soffice')
  })

  it('tries PATH first on Linux, then the usual install places and Flatpak', () => {
    const list = sofficeCandidates('linux', { PATH: '/usr/local/bin' })

    expect(list.slice(0, 2)).toEqual(['/usr/local/bin/soffice', '/usr/local/bin/libreoffice'])
    expect(list).toContain('/usr/lib/libreoffice/program/soffice')
    expect(list.at(-1)).toBe('/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice')
  })
})

describe('convertArgs', () => {
  it('runs headless with a profile of its own', () => {
    expect(convertArgs('/tmp/in/Plan.odt', 'docx', '/tmp/w/out', '/tmp/w/profile')).toEqual([
      '-env:UserInstallation=file:///tmp/w/profile',
      '--headless',
      '--norestore',
      '--nologo',
      '--nolockcheck',
      '--convert-to',
      'docx',
      '--outdir',
      '/tmp/w/out',
      '/tmp/in/Plan.odt'
    ])
  })
})

describe('convertWithLibreOffice', () => {
  it('refuses formats it does not convert to', async () => {
    await expect(convertWithLibreOffice('/tmp/a.odt', 'exe')).rejects.toThrow('not asked for .exe')
  })
})
