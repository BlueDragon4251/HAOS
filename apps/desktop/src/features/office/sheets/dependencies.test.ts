import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/* Herald Office uses Univer's open-source packages only: none of its paid ones may come in, even through another package. */

const lockfile = fileURLToPath(new URL('../../../../../../package-lock.json', import.meta.url))

describe('dependencies', () => {
  it('has no paid Univer packages in the lockfile', () => {
    const text = fs.readFileSync(lockfile, 'utf8')
    const packages = Object.keys((JSON.parse(text) as { packages: Record<string, unknown> }).packages)

    expect(text).not.toContain('@univerjs-pro')
    expect(packages.filter((name) => /@univerjs\/preset-[^/]*-(advanced|collaboration)/.test(name))).toEqual([])
  })

  it('has only openly licensed Univer packages (Apache-2.0, and MIT for its icons)', () => {
    const { packages } = JSON.parse(fs.readFileSync(lockfile, 'utf8')) as { packages: Record<string, { license?: string }> }
    const univer = Object.entries(packages).filter(([name]) => /node_modules\/@univerjs\//.test(name))

    expect(univer.length).toBeGreaterThan(20)
    expect(univer.filter(([, entry]) => entry.license !== 'Apache-2.0' && entry.license !== 'MIT').map(([name]) => name)).toEqual([])
  })
})
