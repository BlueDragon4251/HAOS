import '@univerjs/docs-ui/lib/index.css'
import '@univerjs/docs-ui/facade'
import { type IDocumentData, type Univer, UniverInstanceType } from '@univerjs/core'
import type { FUniver } from '@univerjs/core/facade'
import { UniverDocsPlugin } from '@univerjs/docs'
import DocsUIEnUS from '@univerjs/docs-ui/locale/en-US'
import { UniverDocsUIPlugin } from '@univerjs/docs-ui'
import { createUniver } from './base.ts'

export interface DocsEngine {
  univer: Univer
  api: FUniver
  dispose: () => void
}

/** Univer Docs in `container`, showing `document`. */
export function createDocsEngine(container: HTMLElement, document: Partial<IDocumentData>): DocsEngine {
  const { univer, api } = createUniver({ container, locales: [DocsUIEnUS] })
  univer.registerPlugin(UniverDocsPlugin)
  univer.registerPlugin(UniverDocsUIPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_DOC, document)

  return { univer, api, dispose: () => univer.dispose() }
}
