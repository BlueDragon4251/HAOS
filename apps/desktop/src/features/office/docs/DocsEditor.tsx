import { useEffect, useRef } from 'react'
import type { DocumentSnapshot } from '../../../../shared/office/document.ts'
import type { EditorHandle, OfficeDocument } from '../types.ts'
import { createDocsEngine, type DocsEngine } from '../univer/docs.ts'
import { type Mounted, mountIn, unmount } from '../univer/mount.ts'
import { docsSession } from './store.ts'

const ZOOM_STEPS = [0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 2]

const wordsIn = (text: string): number => (text.replace(/[\u0000-\u001F]/g, ' ').match(/\S+/g) ?? []).length

/** One document in Univer Docs. */
export function DocsEditor({ doc }: { doc: OfficeDocument<DocumentSnapshot> }) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let mounted: Mounted<DocsEngine> | null = null
    let off = () => {}
    let zoom = 1
    const start = (model: DocumentSnapshot) => {
      mounted = mountIn(host.current!, (element) => createDocsEngine(element, model))
      off = mounted.engine.onChange(() => docsSession.changed(doc))
      zoom = 1
    }
    const stop = (later: boolean) => {
      off()
      unmount(mounted, later)
      mounted = null
    }
    const handle: EditorHandle<DocumentSnapshot> = {
      snapshot: () => mounted!.engine.snapshot(),
      load: (model) => {
        stop(false)
        start(model)
      },
      undo: () => mounted?.engine.undo(),
      redo: () => mounted?.engine.redo(),
      // Univer's own footer shows the pages and words.
      status: () => '',
      detail: () => {
        const words = wordsIn(mounted?.engine.text() ?? '')

        return `${words.toLocaleString()} ${words === 1 ? 'word' : 'words'}`
      },
      zoom: (step) => {
        const index = ZOOM_STEPS.findIndex((value) => value >= zoom - 0.001)
        zoom = step === 'reset' ? 1 : (ZOOM_STEPS[Math.max(0, Math.min(ZOOM_STEPS.length - 1, index + (step === 'in' ? 1 : -1)))] ?? 1)
        mounted?.engine.zoom(zoom)
      },
      dispose: () => stop(false)
    }
    start(doc.initial)
    docsSession.attach(doc, handle)

    return () => {
      // The document outlives its view (a closed window keeps it until Herald quits): it keeps what was typed.
      if (mounted) {
        doc.initial = mounted.engine.snapshot()
      }

      if (doc.editor === handle) {
        docsSession.attach(doc, null)
      }

      stop(true)
    }
  }, [doc.key])

  return <div ref={host} className="relative min-w-0 flex-1" />
}
