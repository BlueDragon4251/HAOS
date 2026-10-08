import '../univer/univer.css'
import { useEffect, useMemo, useState } from 'react'
import { officeAppFor, openFormats } from '../../../../shared/office/files.ts'
import { messageOf } from '../../canvas/errors.ts'
import { officeAbilities } from '../session.ts'
import { officeMenus } from '../shell/commands.ts'
import { OfficeWindow } from '../shell/OfficeWindow.tsx'
import { SheetsEditor } from './SheetsEditor.tsx'
import { sheetsSession } from './store.ts'

/** Herald Sheets: spreadsheets on Univer in a Herald window. */
export function SheetsWindow({ payload }: { payload?: Record<string, unknown> }) {
  const [canOpen, setCanOpen] = useState(true)

  useEffect(() => {
    void officeAbilities().then((abilities) => setCanOpen(openFormats('sheets', abilities).length > 0))
  }, [])

  const menus = useMemo(() => officeMenus({ session: sheetsSession, canSave: true }), [])

  const onDropFile = (file: string) => {
    void officeAbilities().then((abilities) => {
      if (officeAppFor(file, abilities) === 'sheets') {
        sheetsSession.open(file).catch((error: unknown) => sheetsSession.notify(`Could not open ${file.split('/').pop()}: ${messageOf(error)}`, 'error'))
      } else {
        sheetsSession.notify(`Herald Sheets does not open ${file.split('/').pop()}`, 'error')
      }
    })
  }

  return (
    <OfficeWindow
      session={sheetsSession}
      menus={menus}
      payload={payload}
      noun="spreadsheet"
      canOpen={canOpen}
      onDropFile={onDropFile}
      start={{ icon: 'sheets', blurb: 'Formulas, number formats, sorting and filters, worked out as you type. CSV files open and save now; Excel workbooks come next.', newLabel: 'New spreadsheet', hint: 'Or drop a CSV file here.' }}
      renderEditor={(doc) => <SheetsEditor doc={doc} />}
    />
  )
}
