import '@univerjs/sheets/facade'
import '@univerjs/engine-formula/facade'
import '@univerjs/sheets-formula/facade'
import '@univerjs/docs/facade'
import { type IDocumentData, type IWorkbookData, LifecycleService, LifecycleStages, LocaleType, LogLevel, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/facade'
import type { FDocument } from '@univerjs/docs/facade'
import { UniverDocsPlugin } from '@univerjs/docs'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverRenderEnginePlugin } from '@univerjs/engine-render'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import type { FWorkbook } from '@univerjs/sheets/facade'
import { CalculationMode, UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'

/*
 * Univer without a window: no chrome and no drawing, only the models, the commands and the
 * formula engine. Hermes's commands use it to change a file that is not open, the same way an open
 * window would change it.
 */

const LOCALES = { [LocaleType.EN_US]: {} }

/**
 * Univer's chrome moves an instance on to Rendered and Steady once it has drawn, and in a browser
 * the formula engine waits for Rendered before it calculates anything; without chrome nothing else
 * would move it on.
 */
function settle(univer: Univer): void {
  const lifecycle = univer.__getInjector().get(LifecycleService)

  for (const stage of [LifecycleStages.Rendered, LifecycleStages.Steady]) {
    if (lifecycle.stage < stage) {
      lifecycle.stage = stage
    }
  }
}

/** Run `work` on a workbook loaded with nothing drawn, then free it. */
export async function withHeadlessWorkbook<T>(snapshot: Partial<IWorkbookData>, work: (workbook: FWorkbook, api: FUniver) => Promise<T> | T): Promise<T> {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: LOCALES, logLevel: LogLevel.ERROR })

  try {
    univer.registerPlugin(UniverFormulaEnginePlugin)
    univer.registerPlugin(UniverSheetsPlugin)
    // A file saved by another app may hold stale results: they are worked out again on load.
    univer.registerPlugin(UniverSheetsFormulaPlugin, { initialFormulaComputing: CalculationMode.FORCED })
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, snapshot)
    settle(univer)
    const api = FUniver.newAPI(univer)
    const workbook = api.getActiveWorkbook()

    if (!workbook) {
      throw new Error('The workbook did not load')
    }

    return await work(workbook, api)
  } finally {
    univer.dispose()
  }
}

/** Run `work` on a document loaded with nothing drawn, then free it. */
export async function withHeadlessDocument<T>(snapshot: Partial<IDocumentData>, work: (document: FDocument, api: FUniver) => Promise<T> | T): Promise<T> {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: LOCALES, logLevel: LogLevel.ERROR })

  try {
    // Docs' text edits look up the render manager; with no chrome it never creates a canvas.
    univer.registerPlugin(UniverRenderEnginePlugin)
    univer.registerPlugin(UniverDocsPlugin)
    univer.createUnit(UniverInstanceType.UNIVER_DOC, snapshot)
    settle(univer)
    const api = FUniver.newAPI(univer)
    const document = api.getActiveDocument()

    if (!document) {
      throw new Error('The document did not load')
    }

    return await work(document, api)
  } finally {
    univer.dispose()
  }
}
