import { useEffect, useRef } from 'react'
import type { WorkbookSnapshot } from '../../../../shared/office/workbook.ts'
import type { EditorHandle, OfficeDocument } from '../types.ts'
import { type Mounted, mountIn, unmount } from '../univer/mount.ts'
import { createSheetsEngine, type SheetsEngine } from '../univer/sheets.ts'
import { sheetsSession } from './store.ts'

/** One workbook in Univer Sheets, its formulas worked out in a worker. */
export function SheetsEditor({ doc }: { doc: OfficeDocument<WorkbookSnapshot> }) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let mounted: Mounted<SheetsEngine> | null = null
    let off = () => {}
    const start = (model: WorkbookSnapshot) => {
      mounted = mountIn(host.current!, (element) => createSheetsEngine(element, model, { worker: true }))
      off = mounted.engine.onChange(() => sheetsSession.changed(doc))
    }
    const stop = (later: boolean) => {
      off()
      unmount(mounted, later)
      mounted = null
    }
    const handle: EditorHandle<WorkbookSnapshot> = {
      snapshot: () => ({ ...mounted!.engine.snapshot(), activeSheetId: mounted!.engine.position().sheetId }),
      load: (model) => {
        stop(false)
        start(model)
      },
      undo: () => mounted?.engine.undo(),
      redo: () => mounted?.engine.redo(),
      status: () => {
        const position = mounted?.engine.position()

        return position ? [position.sheet, position.selection].filter(Boolean).join(' · ') : ''
      },
      detail: () => {
        const position = mounted?.engine.position()

        return position ? `${position.sheet}${position.selection ? `!${position.selection}` : ''}` : undefined
      },
      dispose: () => stop(false)
    }
    start(doc.initial)
    sheetsSession.attach(doc, handle)

    return () => {
      // The workbook outlives its view (a closed window keeps it until Herald quits): it keeps what was typed.
      if (mounted) {
        doc.initial = mounted.engine.snapshot()
      }

      if (doc.editor === handle) {
        sheetsSession.attach(doc, null)
      }

      stop(true)
    }
  }, [doc.key])

  return <div ref={host} className="relative min-w-0 flex-1" />
}
