import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { defaultTransform, imageFileFor, maskFileFor, newManifest, parseManifestText } from '../../shared/canvas/comp-format.ts'
import { PackageWatcher, readAsset, readPackage, writePackage } from './package-io.ts'
import { decodePng } from './png.ts'

const A = '6F1D3C2A-0B7E-4E8A-9C4D-2A1B3C4D5E6F'
const B = 'A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D'

let root = ''

async function project(): Promise<string> {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'canvas-'))

  return path.join(root, 'Poster.comp')
}

afterEach(async () => {
  await fs.rm(root, { recursive: true, force: true })
})

function twoLayers() {
  const manifest = newManifest(8, 4)
  manifest.layers = [
    { id: A, name: 'Background', isVisible: true, transform: defaultTransform(8, 4), imageFile: imageFileFor(A), maskFile: maskFileFor(A), maskEnabled: true },
    { id: B, name: 'Logo', isVisible: true, transform: defaultTransform(2, 2, 3, 1), imageFile: imageFileFor(B) }
  ]
  manifest.activeLayerID = B

  return manifest
}

const rgba = (width: number, height: number, value: number) => ({ width, height, channels: 4 as const, data: new Uint8Array(width * height * 4).fill(value) })
const gray = (width: number, height: number, value: number) => ({ width, height, channels: 1 as const, data: new Uint8Array(width * height).fill(value) })

describe('writePackage and readPackage', () => {
  it('writes a project that reads back the same', async () => {
    const dir = await project()
    const digest = await writePackage(dir, { manifest: twoLayers(), assets: { [imageFileFor(A)]: rgba(8, 4, 200), [maskFileFor(A)]: gray(8, 4, 255), [imageFileFor(B)]: rgba(2, 2, 9) } })
    const read = await readPackage(dir)
    expect(read.digest).toBe(digest)
    expect(read.manifest.layers.map(l => l.name)).toEqual(['Background', 'Logo'])
    expect(Object.keys(read.assets).sort()).toEqual([imageFileFor(A), imageFileFor(B), maskFileFor(A)].sort())
    expect(decodePng(await readAsset(dir, maskFileFor(A)))).toMatchObject({ width: 8, height: 4, channels: 1 })
    // No temporary files are left behind.
    expect((await fs.readdir(dir)).sort()).toEqual(['images', 'manifest.json'])
  })

  it('keeps images it is not given, and removes the ones the manifest drops', async () => {
    const dir = await project()
    await writePackage(dir, { manifest: twoLayers(), assets: { [imageFileFor(A)]: rgba(8, 4, 1), [maskFileFor(A)]: gray(8, 4, 2), [imageFileFor(B)]: rgba(2, 2, 3) } })
    const fewer = twoLayers()
    fewer.layers = fewer.layers.slice(0, 1)
    fewer.activeLayerID = A
    await writePackage(dir, { manifest: fewer, assets: {} })
    expect((await fs.readdir(path.join(dir, 'images'))).sort()).toEqual([imageFileFor(A), maskFileFor(A)].sort())
  })

  it('writes the Finder preview when given one, and drops a stale one otherwise', async () => {
    const dir = await project()
    const assets = { [imageFileFor(A)]: rgba(8, 4, 1), [maskFileFor(A)]: gray(8, 4, 2), [imageFileFor(B)]: rgba(2, 2, 3) }
    await writePackage(dir, { manifest: twoLayers(), assets, preview: new Uint8Array([0xff, 0xd8]) })
    expect(await fs.readdir(path.join(dir, 'QuickLook'))).toEqual(['Preview.jpg'])
    await writePackage(dir, { manifest: twoLayers(), assets: {} })
    await expect(fs.stat(path.join(dir, 'QuickLook'))).rejects.toThrow()
  })

  it('refuses images that do not belong, are the wrong kind, or are missing', async () => {
    const dir = await project()
    await expect(writePackage(dir, { manifest: twoLayers(), assets: { 'other.png': rgba(1, 1, 0) } })).rejects.toThrow(/not part/)
    await expect(writePackage(dir, { manifest: twoLayers(), assets: { [maskFileFor(A)]: rgba(8, 4, 0) } })).rejects.toThrow(/grayscale/)
    await expect(writePackage(dir, { manifest: twoLayers(), assets: { [imageFileFor(A)]: rgba(8, 4, 0) } })).rejects.toThrow(/missing/)
    // Nothing half-written: the failed writes never put a manifest in place.
    await expect(fs.stat(path.join(dir, 'manifest.json'))).rejects.toThrow()
  })

  it('refuses an image that is a link to somewhere else', async () => {
    const dir = await project()
    await writePackage(dir, { manifest: twoLayers(), assets: { [imageFileFor(A)]: rgba(8, 4, 1), [maskFileFor(A)]: gray(8, 4, 2), [imageFileFor(B)]: rgba(2, 2, 3) } })
    const target = path.join(dir, 'images', imageFileFor(B))
    await fs.rm(target)
    await fs.symlink('/etc/hosts', target)
    await expect(readPackage(dir)).rejects.toThrow(/missing/)
  })
})

describe('PackageWatcher', () => {
  const settle = () => new Promise(resolve => setTimeout(resolve, 200))

  it('reports a change made elsewhere, but not Herald saving its own work', async () => {
    const dir = await project()
    const assets = { [imageFileFor(A)]: rgba(8, 4, 1), [maskFileFor(A)]: gray(8, 4, 2), [imageFileFor(B)]: rgba(2, 2, 3) }
    const first = await writePackage(dir, { manifest: twoLayers(), assets })
    const seen: string[] = []
    const watcher = new PackageWatcher(dir, first, contents => seen.push(contents.manifest.layers[1].name), 40)
    watcher.start()

    try {
      // Herald's own save.
      const renamed = twoLayers()
      renamed.layers[1].name = 'Mine'
      await watcher.ownWrite(() => writePackage(dir, { manifest: renamed, assets: {} }))
      await settle()
      expect(seen).toEqual([])

      // Someone else's edit: a half-written manifest first, then the finished one.
      await fs.writeFile(path.join(dir, 'manifest.json'), '{ "format": "com.compositor.project", ')
      await settle()
      const theirs = twoLayers()
      theirs.layers[1].name = 'From Hermes'
      await fs.writeFile(path.join(dir, 'manifest.json'), JSON.stringify(theirs))
      await settle()
      expect(seen).toEqual(['From Hermes'])
      expect(parseManifestText(await fs.readFile(path.join(dir, 'manifest.json'), 'utf8')).layers[1].name).toBe('From Hermes')
    } finally {
      watcher.stop()
    }
  })
})
