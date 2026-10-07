import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { type ModelId, type ModelInfo, MODELS, type ModelProgress, PERMISSIVE_LICENCES } from '../../shared/canvas/models.ts'
import { type Fetcher, ModelStore } from './model-store.ts'

const bytesOf = (size: number, seed: number) => Uint8Array.from({ length: size }, (_, i) => (i * 31 + seed) & 255)
const sha = (bytes: Uint8Array) => crypto.createHash('sha256').update(bytes).digest('hex')

const encoder = bytesOf(3_000_000, 1)
const decoder = bytesOf(1_200_000, 2)
const MODEL: ModelInfo = {
  id: 'efficientsam',
  name: 'Test model',
  purpose: 'Testing',
  licence: 'Apache-2.0',
  source: 'https://example.com',
  files: [
    { name: 'encoder.onnx', url: 'https://example.com/encoder.onnx', bytes: encoder.length, sha256: sha(encoder) },
    { name: 'decoder.onnx', url: 'https://example.com/decoder.onnx', bytes: decoder.length, sha256: sha(decoder) }
  ]
}

/** Serves the files in chunks, as a network would; `tamper` changes one byte of a file. */
function server(options: { tamper?: string; stall?: string } = {}): Fetcher & { requests: string[] } {
  const requests: string[] = []
  const fetcher = (async (url: string, init: { signal: AbortSignal }) => {
    requests.push(url)
    const body = url.endsWith('encoder.onnx') ? encoder.slice() : decoder.slice()

    if (options.tamper && url.endsWith(options.tamper)) {
      body[1000] ^= 1
    }

    let at = 0
    const stream = new ReadableStream<Uint8Array>({
      pull: async (controller) => {
        if (init.signal.aborted) {
          controller.error(new DOMException('Aborted', 'AbortError'))

          return
        }

        if (options.stall && url.endsWith(options.stall) && at > 0) {
          await new Promise((resolve) => setTimeout(resolve, 20))
        }

        if (at >= body.length) {
          controller.close()

          return
        }

        controller.enqueue(body.subarray(at, at + 256 * 1024))
        at += 256 * 1024
      }
    })

    return new Response(stream, { status: 200 })
  }) as Fetcher & { requests: string[] }
  fetcher.requests = requests

  return fetcher
}

let root = ''

beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'herald-models-'))
})

afterEach(async () => {
  await fs.rm(root, { recursive: true, force: true })
})

describe('the model manifest', () => {
  it('lists permissive models with https downloads and full digests', () => {
    for (const model of MODELS) {
      expect(PERMISSIVE_LICENCES).toContain(model.licence)
      expect(model.source).toMatch(/^https:\/\//)

      for (const file of model.files) {
        expect(file.url).toMatch(/^https:\/\//)
        expect(file.sha256).toMatch(/^[0-9a-f]{64}$/)
        expect(file.bytes).toBeGreaterThan(1_000_000)
      }
    }
  })
})

describe('ModelStore', () => {
  it('downloads every file, checks it, and reports progress', async () => {
    const progress: ModelProgress[] = []
    const store = new ModelStore(root, server(), (event) => progress.push(event), [MODEL])
    expect((await store.status())[0]).toMatchObject({ id: 'efficientsam', state: 'missing', bytes: 0 })
    await store.download('efficientsam')
    expect((await store.status())[0]).toMatchObject({ state: 'ready', bytes: encoder.length + decoder.length })
    expect(progress.at(-1)).toEqual({ id: 'efficientsam', received: 4_200_000, total: 4_200_000, outcome: 'done' })
    expect(progress.filter((event) => !event.outcome).length).toBeGreaterThan(1)
    expect(await store.verifiedFile('efficientsam', 'encoder.onnx')).toBe(path.join(root, 'efficientsam', 'encoder.onnx'))
    expect(await fs.readdir(path.join(root, 'efficientsam'))).toEqual(['decoder.onnx', 'encoder.onnx'])
  })

  it('keeps nothing that does not match its digest', async () => {
    const progress: ModelProgress[] = []
    const store = new ModelStore(root, server({ tamper: 'decoder.onnx' }), (event) => progress.push(event), [MODEL])
    await expect(store.download('efficientsam')).rejects.toThrow(/decoder\.onnx did not match its published checksum/)
    expect(await fs.readdir(path.join(root, 'efficientsam'))).toEqual(['encoder.onnx'])
    expect((await store.status())[0].state).toBe('missing')
    expect(progress.at(-1)?.outcome).toEqual({ error: 'decoder.onnx did not match its published checksum; nothing was kept' })
  })

  it('refuses to serve a file changed on disk after it was checked', async () => {
    const fresh = new ModelStore(root, server(), () => {}, [MODEL])
    await fresh.download('efficientsam')
    const file = path.join(root, 'efficientsam', 'decoder.onnx')
    const changed = decoder.slice()
    changed[5] ^= 1
    await fs.writeFile(file, changed)
    // A new session checks the file before it first serves it.
    const later = new ModelStore(root, server(), () => {}, [MODEL])
    await expect(later.verifiedFile('efficientsam', 'decoder.onnx')).rejects.toThrow(/does not match its published checksum/)
    await expect(later.verifiedFile('isnet' as ModelId, 'x.onnx')).rejects.toThrow(/no model called isnet/)
  })

  it('takes up an interrupted download where it stopped, and cancels cleanly', async () => {
    const slow = server({ stall: 'decoder.onnx' })
    const progress: ModelProgress[] = []
    const store = new ModelStore(root, slow, (event) => {
      progress.push(event)

      // Cancel once the second file has begun.
      if (event.received > encoder.length && !event.outcome) {
        store.cancel('efficientsam')
      }
    }, [MODEL])
    await expect(store.download('efficientsam')).rejects.toThrow(/cancelled/)
    expect(progress.at(-1)?.outcome).toBe('cancelled')
    expect(await fs.readdir(path.join(root, 'efficientsam'))).toEqual(['encoder.onnx'])
    const again = server()
    const resumed = new ModelStore(root, again, () => {}, [MODEL])
    await resumed.download('efficientsam')
    expect(again.requests).toEqual(['https://example.com/decoder.onnx'])
    await resumed.remove('efficientsam')
    expect((await resumed.status())[0]).toMatchObject({ state: 'missing', bytes: 0 })
  })
})
