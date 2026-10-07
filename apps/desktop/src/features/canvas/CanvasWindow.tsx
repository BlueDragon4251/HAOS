import { useStore } from '@nanostores/react'
import { IconFolderOpen, IconHandStop, IconPhotoPlus, IconPointer, IconX, IconZoomIn } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { canOpenInCanvas, isProjectPath, projectContaining } from '../../../shared/canvas/files.ts'
import { GlassButton } from '../../components/ui/glass.tsx'
import { cn } from '../../lib/cn.ts'
import { Menu } from '../files/Menu.tsx'
import { deletePicked, nudge, placeImage } from './actions.ts'
import { CloseDialog, NewDocumentDialog } from './dialogs.tsx'
import type { CanvasDocument } from './engine/document.ts'
import { useActiveDocument } from './hooks.ts'
import { LayersPanel } from './LayersPanel.tsx'
import { $dialog, commandLabel, isEnabled, keysLabel, MENUS, runShortcut } from './menus.ts'
import { $activeKey, $conflict, $documents, $notice, activate, notify, openPath, resolveConflict } from './store.ts'
import { $autoSelect, $spaceHeld, $tool, type ToolId, TOOLS } from './tools.ts'
import { $pointer, $views, actualPixels, fitToScreen, forgetView, zoomLabel } from './view-state.ts'
import { Viewport } from './Viewport.tsx'

const TOOL_ICONS: Record<ToolId, React.ReactNode> = {
  move: <IconPointer size={17} />,
  hand: <IconHandStop size={17} />,
  zoom: <IconZoomIn size={17} />
}

const describe = (error: unknown): string => (error instanceof Error ? error.message : String(error))

const isTyping = (target: EventTarget | null): boolean => target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))

function MenuBar({ doc }: { doc: CanvasDocument | null }) {
  const [open, setOpen] = useState<string | null>(null)

  return (
    <div className="flex items-center gap-0.5" role="menubar">
      {MENUS.map((menu) => (
        <div key={menu.id} className="relative">
          <button
            type="button"
            role="menuitem"
            aria-haspopup="menu"
            aria-expanded={open === menu.id}
            onMouseDown={(event) => event.stopPropagation()}
            onClick={() => setOpen(open === menu.id ? null : menu.id)}
            onMouseEnter={() => open && open !== menu.id && setOpen(menu.id)}
            className={cn('h-7 rounded-md px-2.5 text-[12.5px] text-fg-2 hover:bg-white/8 hover:text-fg', open === menu.id && 'bg-white/10 text-fg')}
          >
            {menu.label}
          </button>
          {open === menu.id && (
            <Menu
              align="left"
              className="top-full mt-1 min-w-60"
              onClose={() => setOpen(null)}
              items={menu.items.map((command) => ({
                id: command.id,
                label: commandLabel(command, doc),
                hint: command.keys ? keysLabel(command.keys) : undefined,
                disabled: !isEnabled(command, doc),
                checked: command.checked?.(),
                dividerBefore: command.dividerBefore,
                onSelect: () => command.run(doc)
              }))}
            />
          )}
        </div>
      ))}
    </div>
  )
}

function Tabs({ documents, active }: { documents: CanvasDocument[]; active: CanvasDocument | null }) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto px-2" role="tablist">
      {documents.map((doc) => (
        <div
          key={doc.key}
          role="tab"
          aria-selected={doc === active}
          onClick={() => activate(doc.key)}
          className={cn('group flex h-7 max-w-52 shrink-0 cursor-default items-center gap-1.5 rounded-md pl-2.5 pr-1 text-[12px]', doc === active ? 'bg-white/10 text-fg' : 'text-fg-3 hover:bg-white/5 hover:text-fg-2')}
          title={doc.path ?? doc.name}
        >
          <span className="truncate">{doc.name}</span>
          {doc.modified && <span className="size-1.5 shrink-0 rounded-full bg-fg-3" aria-label="Unsaved changes" />}
          <button
            type="button"
            aria-label={`Close ${doc.name}`}
            onClick={(event) => {
              event.stopPropagation()
              $dialog.set({ kind: 'close', key: doc.key })
            }}
            className="grid size-5 place-items-center rounded text-fg-3 opacity-0 hover:bg-white/10 hover:text-fg group-hover:opacity-100"
          >
            <IconX size={12} />
          </button>
        </div>
      ))}
    </div>
  )
}

function ToolPalette() {
  const tool = useStore($tool)

  return (
    <div className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-line py-2" role="toolbar" aria-orientation="vertical" aria-label="Tools">
      {TOOLS.map((def) => (
        <button
          key={def.id}
          type="button"
          title={`${def.label} (${def.key.toUpperCase()})`}
          aria-label={def.label}
          aria-pressed={tool === def.id}
          onClick={() => $tool.set(def.id)}
          className={cn('grid size-8 place-items-center rounded-lg', tool === def.id ? 'bg-accent/20 text-fg ring-1 ring-accent/50' : 'text-fg-3 hover:bg-white/8 hover:text-fg')}
        >
          {TOOL_ICONS[def.id]}
        </button>
      ))}
    </div>
  )
}

function OptionsBar({ doc }: { doc: CanvasDocument }) {
  const tool = useStore($tool)
  const autoSelect = useStore($autoSelect)

  return (
    <div className="flex h-9 shrink-0 items-center gap-3 border-b border-line px-3 text-[12px] text-fg-2">
      <span className="text-fg-3">{TOOLS.find((def) => def.id === tool)?.label}</span>
      {tool === 'move' && (
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={autoSelect} onChange={(event) => $autoSelect.set(event.target.checked)} />
          Pick the layer under the pointer
        </label>
      )}
      {(tool === 'zoom' || tool === 'hand') && (
        <div className="flex items-center gap-1.5">
          <GlassButton size="sm" variant="ghost" onClick={() => fitToScreen(doc)}>
            Fit on screen
          </GlassButton>
          <GlassButton size="sm" variant="ghost" onClick={() => actualPixels(doc)}>
            100%
          </GlassButton>
        </div>
      )}
    </div>
  )
}

function StatusBar({ doc }: { doc: CanvasDocument | null }) {
  const views = useStore($views)
  const pointer = useStore($pointer)
  const notice = useStore($notice)
  const [now, setNow] = useState(Date.now())
  const fresh = notice && now - notice.at < 6000

  useEffect(() => {
    if (!notice) {
      return
    }

    setNow(Date.now())
    const timer = setTimeout(() => setNow(Date.now()), 6100)

    return () => clearTimeout(timer)
  }, [notice])

  const view = doc ? views[doc.key] : undefined

  return (
    <div className="flex h-7 shrink-0 items-center gap-4 border-t border-line px-3 text-[11.5px] text-fg-3 tabular-nums">
      {doc && (
        <>
          {view && <span>{zoomLabel(view.zoom)}</span>}
          <span>
            {doc.state.width} × {doc.state.height} px
          </span>
          {pointer && (
            <span>
              {pointer.x}, {pointer.y}
            </span>
          )}
        </>
      )}
      <span className={cn('ml-auto truncate', fresh && notice.tone === 'error' && 'text-danger')}>
        {fresh ? notice.message : doc ? (doc.path ? (doc.modified ? 'Edited' : 'Saved') : 'Not saved yet') : ''}
      </span>
    </div>
  )
}

function ConflictBar() {
  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-line bg-warn/10 px-3 py-1.5 text-[12px] text-fg-2">
      <span className="flex-1">This project changed on disk while it had unsaved edits here.</span>
      <GlassButton size="sm" variant="ghost" onClick={() => void resolveConflict('mine')}>
        Keep mine
      </GlassButton>
      <GlassButton size="sm" variant="primary" onClick={() => void resolveConflict('theirs')}>
        Load theirs
      </GlassButton>
    </div>
  )
}

function StartScreen() {
  const open = async () => {
    const file = await window.heraldOS.canvas.pickOpen()

    if (file) {
      openPath(file).catch((error: unknown) => notify(`Could not open ${file.split('/').pop()}: ${describe(error)}`, 'error'))
    }
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col items-center justify-center gap-5 p-8 text-center">
      <div>
        <div className="text-[18px] font-medium text-fg">Herald Canvas</div>
        <div className="mt-1 text-[12.5px] text-fg-3">Layers, masks and blend modes, on the GPU. Hermes can edit along with you.</div>
      </div>
      <div className="flex gap-2">
        <GlassButton variant="primary" onClick={() => $dialog.set({ kind: 'new' })}>
          <IconPhotoPlus size={16} /> New image
        </GlassButton>
        <GlassButton onClick={() => void open()}>
          <IconFolderOpen size={16} /> Open…
        </GlassButton>
      </div>
      <div className="text-[11.5px] text-fg-3">Or drop an image or a .comp project here.</div>
    </div>
  )
}

/** Herald Canvas: a layered image editor in a Herald window. */
export function CanvasWindow({ payload }: { payload?: Record<string, unknown> }) {
  const documents = useStore($documents)
  const doc = useActiveDocument()
  const dialog = useStore($dialog)
  const conflict = useStore($conflict)
  const root = useRef<HTMLDivElement>(null)
  const requested = typeof payload?.path === 'string' ? payload.path : null
  const requestedAt = payload?.at

  // A file handed over by Herald (Edit in Canvas, Hermes, the launcher).
  useEffect(() => {
    if (requested) {
      openPath(requested).catch((error: unknown) => notify(`Could not open ${requested.split('/').pop()}: ${describe(error)}`, 'error'))
    }
  }, [requested, requestedAt])

  // Views of closed documents go with them.
  useEffect(() => {
    const open = new Set(documents.map((entry) => entry.key))
    Object.keys($views.get())
      .filter((key) => !open.has(key))
      .forEach(forgetView)
  }, [documents])

  useEffect(() => {
    const release = () => $spaceHeld.set(false)
    window.addEventListener('blur', release)

    return () => window.removeEventListener('blur', release)
  }, [])

  useEffect(() => {
    if (!$activeKey.get() && documents.length) {
      activate(documents[0].key)
    }
  }, [documents])

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (isTyping(event.target) || dialog) {
      return
    }

    if (runShortcut(event, doc)) {
      event.preventDefault()
      event.stopPropagation()

      return
    }

    if (event.key === ' ') {
      event.preventDefault()
      $spaceHeld.set(true)

      return
    }

    if (event.metaKey || event.ctrlKey || event.altKey) {
      return
    }

    const tool = TOOLS.find((def) => def.key === event.key.toLowerCase())

    if (tool) {
      $tool.set(tool.id)

      return
    }

    if (!doc) {
      return
    }

    if (event.key === 'Backspace' || event.key === 'Delete') {
      event.preventDefault()
      deletePicked(doc)

      return
    }

    const arrows: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }

    if (arrows[event.key] && $tool.get() === 'move') {
      event.preventDefault()
      const step = event.shiftKey ? 10 : 1
      nudge(doc, arrows[event.key][0] * step, arrows[event.key][1] * step)
    }
  }

  const onDrop = (event: React.DragEvent) => {
    const files = [...event.dataTransfer.files].map((file) => window.heraldOS.fs.pathForFile(file)).filter(Boolean)

    if (!files.length) {
      return
    }

    event.preventDefault()

    for (const file of files) {
      const project = isProjectPath(file) || projectContaining(file)

      if (doc && !project && canOpenInCanvas(file)) {
        placeImage(doc, file).catch((error: unknown) => notify(`Could not place ${file.split('/').pop()}: ${describe(error)}`, 'error'))
      } else if (project || canOpenInCanvas(file)) {
        openPath(file).catch((error: unknown) => notify(`Could not open ${file.split('/').pop()}: ${describe(error)}`, 'error'))
      } else {
        notify(`Herald Canvas does not open ${file.split('/').pop()}`, 'error')
      }
    }
  }

  return (
    <div
      ref={root}
      data-canvas-root
      tabIndex={-1}
      onKeyDown={onKeyDown}
      onKeyUp={(event) => event.key === ' ' && $spaceHeld.set(false)}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes('Files')) {
          event.preventDefault()
        }
      }}
      onDrop={onDrop}
      className="relative flex h-full min-h-0 flex-col outline-none"
    >
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line px-2">
        <MenuBar doc={doc} />
        <Tabs documents={documents} active={doc} />
      </div>
      {doc && <OptionsBar doc={doc} />}
      {conflict && conflict.key === doc?.key && <ConflictBar />}
      <div className="flex min-h-0 flex-1">
        <ToolPalette />
        {doc ? <Viewport doc={doc} /> : <StartScreen />}
        {doc && (
          <aside className="flex w-64 shrink-0 flex-col border-l border-line" aria-label="Panels">
            <LayersPanel doc={doc} />
          </aside>
        )}
      </div>
      <StatusBar doc={doc} />
      {dialog?.kind === 'new' && <NewDocumentDialog />}
      {dialog?.kind === 'close' && <CloseDialog docKey={dialog.key} />}
    </div>
  )
}
