import '@univerjs/docs-ui/lib/index.css'
import '@univerjs/docs-ui/facade'
import { CommandType, ICommandService, type IDocumentData, ThemeService, type Univer, UniverInstanceType } from '@univerjs/core'
import type { FUniver } from '@univerjs/core/facade'
import { UniverDocsPlugin } from '@univerjs/docs'
import DocsUIEnUS from '@univerjs/docs-ui/locale/en-US'
import { SetDocZoomRatioCommand, UniverDocsUIPlugin } from '@univerjs/docs-ui'
import { ICanvasColorService } from '@univerjs/engine-render'
import { type DocumentSnapshot, withoutAutomaticColor } from '../../../../shared/office/document.ts'
import { createUniver } from './base.ts'
import { neutralColor } from './theme.ts'

/** The token Univer paints a paged document's desk with. */
const DESK = 'gray.100'

/**
 * Pages as paper: in dark mode Univer inverts every colour it draws, which turns pages black and
 * text white. Docs draws its canvas as it will print, white pages in Univer's own neutral palette
 * and the colours the document has, on a desk that lets Herald's dark glass show through; the
 * chrome around it keeps Herald's palette.
 */
function drawAsPaper(univer: Univer): void {
  const injector = univer.__getInjector()
  const colors = injector.get(ICanvasColorService)
  const theme = injector.get(ThemeService)
  colors.getRenderColor = (color: string) => (color === DESK ? 'rgba(0, 0, 0, 0)' : neutralColor(color))
  // Docs repaints its background whenever the theme is set again.
  theme.setTheme({ ...theme.getCurrentTheme() })
}

export interface DocsEngine {
  univer: Univer
  api: FUniver
  unitId: string
  snapshot: () => DocumentSnapshot
  /** Called after each change to the document's content. */
  onChange: (listener: () => void) => () => void
  undo: () => void
  redo: () => void
  text: () => string
  zoom: (ratio: number) => void
  dispose: () => void
}

/** Univer Docs in `container`, showing `document`. */
export function createDocsEngine(container: HTMLElement, document: DocumentSnapshot): DocsEngine {
  // Univer Docs draws no page without its footer (pages, words, zoom), so it stays.
  const { univer, api } = createUniver({ container, locales: [DocsUIEnUS] })
  univer.registerPlugin(UniverDocsPlugin)
  univer.registerPlugin(UniverDocsUIPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_DOC, document as Partial<IDocumentData>)
  drawAsPaper(univer)
  const unitId = document.id
  const commands = univer.__getInjector().get(ICommandService)
  const listeners = new Set<() => void>()
  const subscription = commands.onCommandExecuted((command) => {
    const params = command.params as { unitId?: string } | undefined

    if (command.type === CommandType.MUTATION && params?.unitId === unitId) {
      listeners.forEach((listener) => listener())
    }
  })
  const doc = () => api.getDocument(unitId)
  // What the editor writes as the colour of typed text when none was chosen.
  const automatic = String(univer.__getInjector().get(ThemeService).getColorFromTheme('gray.900'))

  return {
    univer,
    api,
    unitId,
    snapshot: () => withoutAutomaticColor(doc()!.save() as DocumentSnapshot, automatic),
    onChange: (listener) => {
      listeners.add(listener)

      return () => listeners.delete(listener)
    },
    undo: () => void doc()?.undo(),
    redo: () => void doc()?.redo(),
    text: () => doc()?.getBody().dataStream ?? '',
    zoom: (ratio) => void commands.executeCommand(SetDocZoomRatioCommand.id, { unitId, zoomRatio: ratio }),
    dispose: () => {
      subscription.dispose()
      listeners.clear()
      univer.dispose()
    }
  }
}
