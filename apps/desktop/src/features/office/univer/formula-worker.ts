import { LocaleType, LogLevel, Univer } from '@univerjs/core'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverRPCWorkerThreadPlugin } from '@univerjs/rpc'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverSheetsFilterPlugin } from '@univerjs/sheets-filter'
import { UniverRemoteSheetsFormulaPlugin } from '@univerjs/sheets-formula'

/* Herald Sheets' formulas, worked out off the window's thread: the window sends its edits here and gets results back. */

const univer = new Univer({ locale: LocaleType.EN_US, logLevel: LogLevel.WARN })
univer.registerPlugin(UniverSheetsPlugin, { onlyRegisterFormulaRelatedMutations: true })
// Filters come over too: formulas such as SUBTOTAL leave out the rows a filter hides.
univer.registerPlugin(UniverSheetsFilterPlugin)
univer.registerPlugin(UniverFormulaEnginePlugin)
univer.registerPlugin(UniverRPCWorkerThreadPlugin)
univer.registerPlugin(UniverRemoteSheetsFormulaPlugin)
