import { describe, expect, it } from 'vitest'
import { featureWorkbook, handmadePackage, normalized } from '../../../../shared/office/xlsx/fixtures.ts'
import { workbookFromXlsx } from '../../../../shared/office/xlsx/read.ts'
import { xlsxFromWorkbook } from '../../../../shared/office/xlsx/write.ts'
import { withHeadlessSheets } from './headless.ts'

/* The way a workbook goes in the app: read, loaded into Univer, saved from Univer's own snapshot, and read again. */

async function throughUniver(bytes: Uint8Array) {
  const direct = await workbookFromXlsx(bytes, { id: 'book', name: 'Book' })
  const { snapshot } = await withHeadlessSheets(direct.workbook, () => undefined)
  const written = await xlsxFromWorkbook(snapshot)
  const again = await workbookFromXlsx(written.bytes, { id: 'book', name: 'Book' })

  return { direct, again, losses: written.losses }
}

describe('a workbook through Univer and back', () => {
  it('keeps every mapped feature of the feature workbook', async () => {
    const { direct, again, losses } = await throughUniver(await featureWorkbook())

    expect(losses).toEqual([])
    expect(normalized(again.workbook)).toEqual(normalized(direct.workbook))
  })

  it('keeps a package another app wrote', async () => {
    const { direct, again } = await throughUniver(await handmadePackage())

    expect(normalized(again.workbook)).toEqual(normalized(direct.workbook))
  })
})
