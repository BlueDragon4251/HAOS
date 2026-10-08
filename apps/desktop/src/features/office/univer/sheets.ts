import '@univerjs/docs-ui/lib/index.css'
import '@univerjs/sheets-ui/lib/index.css'
import '@univerjs/sheets-formula-ui/lib/index.css'
import '@univerjs/sheets-numfmt-ui/lib/index.css'
import '@univerjs/sheets-filter-ui/lib/index.css'
import '@univerjs/sheets-sort-ui/lib/index.css'
import '@univerjs/sheets-conditional-formatting-ui/lib/index.css'
import '@univerjs/sheets-data-validation-ui/lib/index.css'
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
import { type IWorkbookData, type Univer, UniverInstanceType } from '@univerjs/core'
import type { FUniver } from '@univerjs/core/facade'
import { UniverDataValidationPlugin } from '@univerjs/data-validation'
import { UniverDocsPlugin } from '@univerjs/docs'
import DocsUIEnUS from '@univerjs/docs-ui/locale/en-US'
import { UniverDocsUIPlugin } from '@univerjs/docs-ui'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
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
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import SheetsFormulaEnUS from '@univerjs/sheets-formula/locale/en-US'
import SheetsFormulaUIEnUS from '@univerjs/sheets-formula-ui/locale/en-US'
import { UniverSheetsFormulaUIPlugin } from '@univerjs/sheets-formula-ui'
import { UniverSheetsNumfmtPlugin } from '@univerjs/sheets-numfmt'
import SheetsNumfmtUIEnUS from '@univerjs/sheets-numfmt-ui/locale/en-US'
import { UniverSheetsNumfmtUIPlugin } from '@univerjs/sheets-numfmt-ui'
import { UniverSheetsSortPlugin } from '@univerjs/sheets-sort'
import SheetsSortUIEnUS from '@univerjs/sheets-sort-ui/locale/en-US'
import { UniverSheetsSortUIPlugin } from '@univerjs/sheets-sort-ui'
import SheetsUIEnUS from '@univerjs/sheets-ui/locale/en-US'
import { UniverSheetsUIPlugin } from '@univerjs/sheets-ui'
import { createUniver } from './base.ts'

export interface SheetsEngine {
  univer: Univer
  api: FUniver
  dispose: () => void
}

/** Univer Sheets in `container`, showing `workbook`; with `worker`, formulas are worked out in a worker. */
export function createSheetsEngine(container: HTMLElement, workbook: Partial<IWorkbookData>, options: { worker?: boolean } = {}): SheetsEngine {
  const { univer, api } = createUniver({
    container,
    locales: [DocsUIEnUS, SheetsEnUS, SheetsUIEnUS, SheetsFormulaEnUS, SheetsFormulaUIEnUS, SheetsNumfmtUIEnUS, SheetsFilterUIEnUS, SheetsSortUIEnUS, SheetsConditionalFormattingUIEnUS, SheetsDataValidationUIEnUS]
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
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, workbook)

  return {
    univer,
    api,
    dispose: () => {
      univer.dispose()
      remote?.terminate()
    }
  }
}
