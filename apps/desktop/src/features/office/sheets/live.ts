import { IUniverInstanceService } from '@univerjs/core'
import { baseName, extensionOf } from '../../../../shared/office/files.ts'
import type { WorkbookSnapshot } from '../../../../shared/office/workbook.ts'
import type { OfficeAdapter } from '../types.ts'
import type { SheetsEngine } from '../univer/sheets.ts'
import { withHeadlessSheets } from './headless.ts'
import type { SheetsTarget } from './model.ts'

/*
 * Where a command's change lands: the workbook open in a window (live, one step to undo, saved as
 * the person's own edits are), or a file on disk, loaded with nothing drawn, changed and written
 * back. A file holding something Herald Sheets cannot keep is not rewritten behind the person's
 * back: it has to be opened, so the fidelity report comes first.
 */

const engines = new Map<string, SheetsEngine>()

/** A document's view has its engine (or lost it): commands reach the live workbook through it. */
export function setLiveEngine(docKey: string, engine: SheetsEngine | null): void {
  if (engine) {
    engines.set(docKey, engine)
  } else {
    engines.delete(docKey)
  }
}

/** The live workbook of an open document, while its view is mounted. */
export function liveTarget(docKey: string): SheetsTarget | null {
  const engine = engines.get(docKey)
  const workbook = engine?.api.getWorkbook(engine.unitId)

  return engine && workbook ? { univer: engine.univer, workbook } : null
}

/** Run one of Univer's own commands (sort, filter, find) in an open document, on its selection. */
export function runInDocument(docKey: string, command: string, params?: object): void {
  const engine = engines.get(docKey)

  if (!engine) {
    return
  }

  // A menu outside the sheet has the focus: Univer runs its commands on the unit that has it.
  engine.univer.__getInjector().get(IUniverInstanceService).focusUnit(engine.unitId)
  void engine.api.executeCommand(command, params)
}

/** The selection in an open document's sheet in front, as a range and its sheet's name. */
export function selectionIn(docKey: string): { sheet: string; range: string } | null {
  const sheet = liveTarget(docKey)?.workbook.getActiveSheet()
  const range = sheet?.getSelection()?.getActiveRange()

  return sheet && range ? { sheet: sheet.getSheetName(), range: range.getA1Notation() } : null
}

export interface FileAccess {
  read: (path: string) => Promise<{ bytes: Uint8Array }>
  write: (path: string, bytes: Uint8Array) => Promise<unknown>
}

/** Change a workbook file that is not open: read, change with nothing drawn, write back. */
export async function changeFile<T>(path: string, change: (target: SheetsTarget) => Promise<T> | T, adapter: OfficeAdapter<WorkbookSnapshot>, io: FileAccess): Promise<{ result: T; workbook: WorkbookSnapshot }> {
  const extension = extensionOf(path)
  const name = baseName(path)
  const read = await adapter.read((await io.read(path)).bytes, extension, name)

  if (read.notes.length) {
    throw new Error(`${name}${extension} has things Herald Sheets cannot keep (${read.notes[0].replace(/\.$/, '')}${read.notes.length > 1 ? `, and ${read.notes.length - 1} more` : ''}): open it in Herald Sheets to change it`)
  }

  const { result, snapshot } = await withHeadlessSheets(read.model, ({ univer, workbook }) => change({ univer, workbook }))
  const written = await adapter.write(snapshot, extension, read.layout)

  if (written.losses.length) {
    throw new Error(`Saving ${name}${extension} would lose something (${written.losses[0].replace(/\.$/, '')}): open it in Herald Sheets to change it`)
  }

  await io.write(path, written.bytes)

  return { result, workbook: snapshot }
}
