import '@univerjs/docs-ui/lib/index.css'
import '@univerjs/sheets-ui/lib/index.css'
import '@univerjs/sheets-formula-ui/lib/index.css'
import '@univerjs/sheets-numfmt-ui/lib/index.css'
import '@univerjs/sheets-filter-ui/lib/index.css'
import '@univerjs/sheets-sort-ui/lib/index.css'
import '@univerjs/sheets-conditional-formatting-ui/lib/index.css'
import '@univerjs/sheets-data-validation-ui/lib/index.css'
import '@univerjs/find-replace/lib/index.css'
import '@univerjs/sheets-hyper-link-ui/lib/index.css'
import '@univerjs/sheets/facade'
import '@univerjs/ui/facade'
import '@univerjs/docs-ui/facade'
import '@univerjs/sheets-ui/facade'
import '@univerjs/engine-formula/facade'
import '@univerjs/sheets-formula/facade'
import '@univerjs/sheets-numfmt/facade'
import '@univerjs/sheets-filter/facade'
import '@univerjs/sheets-sort/facade'
import '@univerjs/sheets-conditional-formatting/facade'
import '@univerjs/sheets-data-validation/facade'
import '@univerjs/sheets-find-replace/facade'
import '@univerjs/sheets-hyper-link/facade'
import '@univerjs/sheets-hyper-link-ui/facade'
import { CommandType, ICommandService, type IWorkbookData, ThemeService, type Univer, UniverInstanceType } from '@univerjs/core'
import type { FUniver } from '@univerjs/core/facade'
import { UniverDataValidationPlugin } from '@univerjs/data-validation'
import { UniverDocsPlugin } from '@univerjs/docs'
import DocsUIEnUS from '@univerjs/docs-ui/locale/en-US'
import { UniverDocsUIPlugin } from '@univerjs/docs-ui'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import FindReplaceEnUS from '@univerjs/find-replace/locale/en-US'
import { UniverFindReplacePlugin } from '@univerjs/find-replace'
import { UniverRPCMainThreadPlugin } from '@univerjs/rpc'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import SheetsEnUS from '@univerjs/sheets/locale/en-US'
import { UniverSheetsConditionalFormattingPlugin } from '@univerjs/sheets-conditional-formatting'
import SheetsConditionalFormattingUIEnUS from '@univerjs/sheets-conditional-formatting-ui/locale/en-US'
import { UniverSheetsConditionalFormattingUIPlugin } from '@univerjs/sheets-conditional-formatting-ui'
import { UniverSheetsDataValidationPlugin } from '@univerjs/sheets-data-validation'
import SheetsDataValidationUIEnUS from '@univerjs/sheets-data-validation-ui/locale/en-US'
import { UniverSheetsDataValidationUIPlugin } from '@univerjs/sheets-data-validation-ui'
import { UniverSheetsFilterPlugin } from '@univerjs/sheets-filter'
import SheetsFilterUIEnUS from '@univerjs/sheets-filter-ui/locale/en-US'
import { UniverSheetsFilterUIPlugin } from '@univerjs/sheets-filter-ui'
import { UniverSheetsFindReplacePlugin } from '@univerjs/sheets-find-replace'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import SheetsFormulaEnUS from '@univerjs/sheets-formula/locale/en-US'
import SheetsFormulaUIEnUS from '@univerjs/sheets-formula-ui/locale/en-US'
import { UniverSheetsFormulaUIPlugin } from '@univerjs/sheets-formula-ui'
import SheetsHyperLinkEnUS from '@univerjs/sheets-hyper-link/locale/en-US'
import { UniverSheetsHyperLinkPlugin } from '@univerjs/sheets-hyper-link'
import SheetsHyperLinkUIEnUS from '@univerjs/sheets-hyper-link-ui/locale/en-US'
import { UniverSheetsHyperLinkUIPlugin } from '@univerjs/sheets-hyper-link-ui'
import { UniverSheetsNumfmtPlugin } from '@univerjs/sheets-numfmt'
import SheetsNumfmtUIEnUS from '@univerjs/sheets-numfmt-ui/locale/en-US'
import { UniverSheetsNumfmtUIPlugin } from '@univerjs/sheets-numfmt-ui'
import { UniverSheetsSortPlugin } from '@univerjs/sheets-sort'
import SheetsSortUIEnUS from '@univerjs/sheets-sort-ui/locale/en-US'
import { UniverSheetsSortUIPlugin } from '@univerjs/sheets-sort-ui'
import SheetsUIEnUS from '@univerjs/sheets-ui/locale/en-US'
import { UniverSheetsUIPlugin } from '@univerjs/sheets-ui'
import { withoutAutomaticColor, type WorkbookSnapshot } from '../../../../shared/office/workbook.ts'
import { createUniver } from './base.ts'

export interface SheetsEngine {
  univer: Univer
  api: FUniver
  unitId: string
  snapshot: () => WorkbookSnapshot
  /** Called after each change to the workbook's content (not formula results or selection). */
  onChange: (listener: () => void) => () => void
  undo: () => void
  redo: () => void
  /** The sheet in front and the selection on it: "Sheet1", "B2:D9". */
  position: () => { sheetId: string | undefined; sheet: string; selection: string | undefined }
  dispose: () => void
}

/** Univer Sheets in `container`, showing `workbook`; with `worker`, formulas are worked out in a worker. */
export function createSheetsEngine(container: HTMLElement, workbook: WorkbookSnapshot | Partial<IWorkbookData>, options: { worker?: boolean } = {}): SheetsEngine {
  const { univer, api } = createUniver({
    container,
    locales: [DocsUIEnUS, SheetsEnUS, SheetsUIEnUS, SheetsFormulaEnUS, SheetsFormulaUIEnUS, SheetsNumfmtUIEnUS, SheetsFilterUIEnUS, SheetsSortUIEnUS, SheetsConditionalFormattingUIEnUS, SheetsDataValidationUIEnUS, FindReplaceEnUS, SheetsHyperLinkEnUS, SheetsHyperLinkUIEnUS]
  })
  const remote = options.worker ? new Worker(new URL('./formula-worker.ts', import.meta.url), { type: 'module', name: 'herald-sheets-formulas' }) : null
  univer.registerPlugin(UniverDocsPlugin)
  univer.registerPlugin(UniverDocsUIPlugin)

  if (remote) {
    univer.registerPlugin(UniverRPCMainThreadPlugin, { workerURL: remote })
  }

  univer.registerPlugin(UniverFormulaEnginePlugin, { notExecuteFormula: Boolean(remote) })
  univer.registerPlugin(UniverSheetsPlugin, { notExecuteFormula: Boolean(remote) })
  univer.registerPlugin(UniverSheetsUIPlugin)
  univer.registerPlugin(UniverSheetsNumfmtPlugin)
  univer.registerPlugin(UniverSheetsNumfmtUIPlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin, { notExecuteFormula: Boolean(remote) })
  univer.registerPlugin(UniverSheetsFormulaUIPlugin)
  univer.registerPlugin(UniverSheetsFilterPlugin)
  univer.registerPlugin(UniverSheetsFilterUIPlugin)
  univer.registerPlugin(UniverSheetsSortPlugin)
  univer.registerPlugin(UniverSheetsSortUIPlugin)
  univer.registerPlugin(UniverSheetsConditionalFormattingPlugin)
  univer.registerPlugin(UniverSheetsConditionalFormattingUIPlugin)
  univer.registerPlugin(UniverDataValidationPlugin)
  univer.registerPlugin(UniverSheetsDataValidationPlugin)
  univer.registerPlugin(UniverSheetsDataValidationUIPlugin)
  univer.registerPlugin(UniverFindReplacePlugin)
  univer.registerPlugin(UniverSheetsFindReplacePlugin)
  univer.registerPlugin(UniverSheetsHyperLinkPlugin)
  univer.registerPlugin(UniverSheetsHyperLinkUIPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, workbook as Partial<IWorkbookData>)
  const unitId = String(workbook.id)
  const commands = univer.__getInjector().get(ICommandService)
  const listeners = new Set<() => void>()
  const subscription = commands.onCommandExecuted((command, executed) => {
    const params = command.params as { unitId?: string } | undefined
    const echo = executed?.onlyLocal || executed?.fromCollab || executed?.fromChangeset || executed?.syncOnly

    if (command.type === CommandType.MUTATION && params?.unitId === unitId && !echo && !command.id.startsWith('formula.')) {
      listeners.forEach((listener) => listener())
    }
  })
  const book = () => api.getWorkbook(unitId)
  // What the cell editor writes as the colour of typed text when none was chosen.
  const automatic = String(univer.__getInjector().get(ThemeService).getColorFromTheme('gray.900'))

  return {
    univer,
    api,
    unitId,
    snapshot: () => withoutAutomaticColor(book()!.save() as unknown as WorkbookSnapshot, automatic),
    onChange: (listener) => {
      listeners.add(listener)

      return () => listeners.delete(listener)
    },
    undo: () => void book()?.undo(),
    redo: () => void book()?.redo(),
    position: () => {
      const sheet = book()?.getActiveSheet()

      return { sheetId: sheet?.getSheetId(), sheet: sheet?.getSheetName() ?? '', selection: sheet?.getSelection()?.getActiveRange()?.getA1Notation() }
    },
    dispose: () => {
      subscription.dispose()
      listeners.clear()
      univer.dispose()
      remote?.terminate()
    }
  }
}
