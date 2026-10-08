import '../univer/univer.css'
import { useEffect, useMemo, useState } from 'react'
import { officeAppFor, openFormats } from '../../../../shared/office/files.ts'
import { messageOf } from '../../canvas/errors.ts'
import { officeAbilities } from '../session.ts'
import { officeMenus } from '../shell/commands.ts'
import { OfficeWindow } from '../shell/OfficeWindow.tsx'
import { DocsEditor } from './DocsEditor.tsx'
import { docsSession } from './store.ts'

const zoom = (step: 'in' | 'out' | 'reset') => () => docsSession.active()?.editor?.zoom?.(step)

/** Herald Docs: documents on Univer in a Herald window. */
export function DocsWindow({ payload }: { payload?: Record<string, unknown> }) {
  const [canOpen, setCanOpen] = useState(true)

  useEffect(() => {
    void officeAbilities().then((abilities) => setCanOpen(openFormats('docs', abilities).length > 0))
  }, [])

  const menus = useMemo(
    () =>
      officeMenus({
        session: docsSession,
        canSave: true,
        menus: [
          {
            id: 'view',
            label: 'View',
            items: [
              { id: 'zoom-in', label: 'Zoom In', keys: 'mod+=', enabled: () => Boolean(docsSession.active()), run: zoom('in') },
              { id: 'zoom-out', label: 'Zoom Out', keys: 'mod+-', enabled: () => Boolean(docsSession.active()), run: zoom('out') },
              { id: 'zoom-reset', label: 'Actual Size', keys: 'mod+0', enabled: () => Boolean(docsSession.active()), run: zoom('reset') }
            ]
          }
        ]
      }),
    []
  )

  const onDropFile = (file: string) => {
    void officeAbilities().then((abilities) => {
      if (officeAppFor(file, abilities) === 'docs') {
        docsSession.open(file).catch((error: unknown) => docsSession.notify(`Could not open ${file.split('/').pop()}: ${messageOf(error)}`, 'error'))
      } else {
        docsSession.notify(`Herald Docs does not open ${file.split('/').pop()}`, 'error')
      }
    })
  }

  return (
    <OfficeWindow
      session={docsSession}
      menus={menus}
      payload={payload}
      noun="document"
      canOpen={canOpen}
      onDropFile={onDropFile}
      start={{ icon: 'docs', blurb: 'Write with headings, lists and styles on real pages. Markdown and plain text open and save now; Word documents come next.', newLabel: 'New document', hint: 'Or drop a Markdown or text file here.' }}
      renderEditor={(doc) => <DocsEditor doc={doc} />}
    />
  )
}
