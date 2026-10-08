import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { digestOfBytes, FileWatcher, stampOf } from './file-watch.ts'

let root = ''
const watchers: FileWatcher[] = []

async function fixture(content: string): Promise<string> {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'office-watch-'))
  const file = path.join(root, 'Budget.csv')
  await fs.writeFile(file, content)

  return file
}

/** A watcher on `file` that reports into a list; short delays keep the tests quick. */
async function follow(file: string, known: string | null) {
  const seen: (string | null)[] = []
  const watcher = new FileWatcher(file, known, (digest) => seen.push(digest), 40, 150)
  watchers.push(watcher)
  watcher.start()

  return { watcher, seen }
}

const until = async (test: () => boolean, ms = 3000) => {
  const end = Date.now() + ms

  while (!test() && Date.now() < end) {
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
}

afterEach(async () => {
  watchers.splice(0).forEach((watcher) => watcher.stop())
  await fs.rm(root, { recursive: true, force: true })
})

describe('stampOf', () => {
  it('digests the content, the same way as the bytes', async () => {
    const file = await fixture('a,b\n')
    const stamp = await stampOf(file)

    expect(stamp?.digest).toBe(digestOfBytes(new TextEncoder().encode('a,b\n')))
    expect(stamp?.size).toBe(4)
    expect(await stampOf(path.join(root, 'missing.csv'))).toBeNull()
  })
})

describe('FileWatcher', () => {
  it('reports an edit made in place and a save by rename', async () => {
    const file = await fixture('one\n')
    const { seen } = await follow(file, (await stampOf(file))!.digest)

    await fs.writeFile(file, 'two\n')
    await until(() => seen.length === 1)
    expect(seen).toEqual([digestOfBytes(new TextEncoder().encode('two\n'))])

    const temporary = path.join(root, '.Budget.csv.tmp')
    await fs.writeFile(temporary, 'three\n')
    await fs.rename(temporary, file)
    await until(() => seen.length === 2)
    expect(seen[1]).toBe(digestOfBytes(new TextEncoder().encode('three\n')))
  })

  it('reports a change that landed before it started, against the version the window loaded', async () => {
    const file = await fixture('loaded\n')
    const loaded = (await stampOf(file))!.digest
    await fs.writeFile(file, 'changed meanwhile\n')
    const { watcher, seen } = await follow(file, loaded)

    await watcher.check()
    expect(seen).toEqual([digestOfBytes(new TextEncoder().encode('changed meanwhile\n'))])
  })

  it('does not report its own window’s saves, nor a write that changes nothing', async () => {
    const file = await fixture('a\n')
    const { watcher, seen } = await follow(file, (await stampOf(file))!.digest)

    await watcher.ownWrite(async () => {
      await fs.writeFile(file, 'saved by Herald\n')

      return digestOfBytes(new TextEncoder().encode('saved by Herald\n'))
    })
    await fs.writeFile(file, 'saved by Herald\n')
    await new Promise((resolve) => setTimeout(resolve, 400))
    expect(seen).toEqual([])
  })

  it('reports the file going away as null, and coming back', async () => {
    const file = await fixture('a\n')
    const { seen } = await follow(file, (await stampOf(file))!.digest)

    await fs.rm(file)
    await until(() => seen.length === 1)
    expect(seen).toEqual([null])

    await fs.writeFile(file, 'back\n')
    await until(() => seen.length === 2)
    expect(seen[1]).toBe(digestOfBytes(new TextEncoder().encode('back\n')))
  })
})
