import { IconAlignCenter, IconAlignLeft, IconAlignRight, IconBold, IconChevronDown, IconCircle, IconItalic, IconLetterT, IconMinus, IconPlayerPlay, IconPlus, IconSquare } from '@tabler/icons-react'
import { useMemo, useState } from 'react'
import { cn } from '../../../lib/cn.ts'
import { Menu } from '../../files/Menu.tsx'
import type { OfficeCommand } from '../shell/commands.ts'
import { officeMenus } from '../shell/commands.ts'
import { OfficeWindow } from '../shell/OfficeWindow.tsx'
import type { OfficeDocument } from '../types.ts'
import { addElement, addSlide, arrangeElement, type Deck, duplicateSlide, LAYOUT_NAMES, type Layout, removeSlide, shapeBox, SLIDE_SIZE, type SlideElement, textBox, updateElement } from './deck.ts'
import type { SlidesDocument } from './model.ts'
import { Present, startPresenting } from './Present.tsx'
import { SlideEditor, useDeck } from './SlideEditor.tsx'
import { decks, slidesSession } from './store.ts'

const live = (): SlidesDocument | undefined => {
  const doc = slidesSession.active()

  return doc ? decks.get(doc.key) : undefined
}

const TEXT_SIZES = [10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 48, 56, 64, 72, 96]
const SWATCHES = ['#1b2340', '#ffffff', '#2f7dff', '#36e6a6', '#f2c25e', '#ff6d6d']

function newSlide(layout: Layout): void {
  const doc = live()

  if (doc) {
    const { deck, slideId } = addSlide(doc.history.present, layout, doc.slide.id)
    doc.commit(deck, 'New Slide', { slideId, selected: null })
  }
}

function insert(kind: 'text' | 'rectangle' | 'ellipse'): void {
  const doc = live()

  if (!doc) {
    return
  }

  const theme = doc.history.present.theme
  const element: SlideElement =
    kind === 'text'
      ? textBox({ x: SLIDE_SIZE.width / 2 - 180, y: SLIDE_SIZE.height / 2 - 30, width: 360, height: 60, placeholder: 'Type here' }, theme)
      : shapeBox({ x: SLIDE_SIZE.width / 2 - 120, y: SLIDE_SIZE.height / 2 - 70, width: 240, height: 140, shape: kind, radius: kind === 'rectangle' ? 12 : 0 }, theme)
  doc.commit(addElement(doc.history.present, doc.slide.id, element), kind === 'text' ? 'New Text Box' : 'New Shape', { selected: element.id })

  if (kind === 'text') {
    doc.select(element.id, true)
  }
}

function restyle(patch: Partial<SlideElement>, label: string): void {
  const doc = live()
  const selected = doc?.slide.elements.find((element) => element.id === doc.selected)

  if (doc && selected) {
    doc.commit(updateElement(doc.history.present, doc.slide.id, selected.id, patch), label, { selected: selected.id })
  }
}

function present(fromStart: boolean): void {
  const active = slidesSession.active()
  const doc = live()

  if (active && doc) {
    startPresenting(active.key, fromStart ? 0 : doc.index)
  }
}

function ToolButton({ label, onClick, active, children, disabled }: { label: string; onClick: () => void; active?: boolean; children: React.ReactNode; disabled?: boolean }) {
  return (
    <button type="button" aria-label={label} title={label} disabled={disabled} onClick={onClick} className={cn('grid h-7 min-w-7 place-items-center rounded-md px-1.5 text-fg-2 hover:bg-white/8 hover:text-fg disabled:opacity-40 [&_svg]:size-4', active && 'bg-white/12 text-fg')}>
      {children}
    </button>
  )
}

function Toolbar({ docKey }: { docKey: string }) {
  const doc = decks.get(docKey)
  useDeck(doc)
  const [layouts, setLayouts] = useState(false)
  const selected = doc?.slide.elements.find((element) => element.id === doc.selected)
  const text = selected?.kind === 'text' ? selected : null

  return (
    <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line px-2 text-[12px]">
      <div className="relative flex">
        <button type="button" onClick={() => newSlide('title-body')} className="flex h-7 items-center gap-1.5 rounded-l-md pl-2 pr-1.5 text-fg-2 hover:bg-white/8 hover:text-fg">
          <IconPlus size={15} /> New slide
        </button>
        <button type="button" aria-label="New slide with a layout" onMouseDown={(event) => event.stopPropagation()} onClick={() => setLayouts(!layouts)} className="grid h-7 w-5 place-items-center rounded-r-md text-fg-3 hover:bg-white/8 hover:text-fg">
          <IconChevronDown size={13} />
        </button>
        {layouts && (
          <Menu align="left" className="top-full mt-1" onClose={() => setLayouts(false)} items={(Object.keys(LAYOUT_NAMES) as Layout[]).map((layout) => ({ id: layout, label: LAYOUT_NAMES[layout], onSelect: () => newSlide(layout) }))} />
        )}
      </div>
      <span className="mx-1 h-5 w-px bg-line" />
      <ToolButton label="Text box" onClick={() => insert('text')}>
        <IconLetterT />
      </ToolButton>
      <ToolButton label="Rectangle" onClick={() => insert('rectangle')}>
        <IconSquare />
      </ToolButton>
      <ToolButton label="Ellipse" onClick={() => insert('ellipse')}>
        <IconCircle />
      </ToolButton>
      {text && (
        <>
          <span className="mx-1 h-5 w-px bg-line" />
          <ToolButton label="Bold" active={text.bold} onClick={() => restyle({ bold: !text.bold }, 'Bold')}>
            <IconBold />
          </ToolButton>
          <ToolButton label="Italic" active={text.italic} onClick={() => restyle({ italic: !text.italic }, 'Italic')}>
            <IconItalic />
          </ToolButton>
          <ToolButton label="Smaller text" onClick={() => restyle({ size: [...TEXT_SIZES].reverse().find((size) => size < text.size) ?? text.size }, 'Text Size')}>
            <IconMinus />
          </ToolButton>
          <span className="w-7 text-center text-fg-2 tabular-nums">{text.size}</span>
          <ToolButton label="Larger text" onClick={() => restyle({ size: TEXT_SIZES.find((size) => size > text.size) ?? text.size }, 'Text Size')}>
            <IconPlus />
          </ToolButton>
          <ToolButton label="Align left" active={text.align === 'left'} onClick={() => restyle({ align: 'left' }, 'Align')}>
            <IconAlignLeft />
          </ToolButton>
          <ToolButton label="Center" active={text.align === 'center'} onClick={() => restyle({ align: 'center' }, 'Align')}>
            <IconAlignCenter />
          </ToolButton>
          <ToolButton label="Align right" active={text.align === 'right'} onClick={() => restyle({ align: 'right' }, 'Align')}>
            <IconAlignRight />
          </ToolButton>
        </>
      )}
      {selected && (
        <>
          <span className="mx-1 h-5 w-px bg-line" />
          {SWATCHES.map((color) => (
            <button
              key={color}
              type="button"
              aria-label={`Colour ${color}`}
              onClick={() => restyle(selected.kind === 'text' ? { color } : { fill: color }, 'Colour')}
              className={cn('size-5 rounded-full border border-line-strong', (selected.kind === 'text' ? selected.color : selected.fill) === color && 'ring-2 ring-accent')}
              style={{ background: color }}
            />
          ))}
        </>
      )}
      <button type="button" onClick={() => present(false)} className="ml-auto flex h-7 items-center gap-1.5 rounded-md bg-accent px-2.5 text-[12px] font-medium text-accent-fg hover:bg-accent-strong">
        <IconPlayerPlay size={14} /> Present
      </button>
    </div>
  )
}

const onDeck = (run: (doc: SlidesDocument) => void) => () => {
  const doc = live()

  if (doc) {
    run(doc)
  }
}

const hasDeck = () => Boolean(live())
const hasSelection = () => Boolean(live()?.selected)

const duplicate = onDeck((doc) => {
  const { deck, slideId } = duplicateSlide(doc.history.present, doc.slide.id)
  doc.commit(deck, 'Duplicate Slide', { slideId, selected: null })
})

const SLIDE_COMMANDS: OfficeCommand[] = [
  { id: 'new-slide', label: 'New Slide', keys: 'mod+shift+n', enabled: hasDeck, run: () => newSlide('title-body') },
  { id: 'duplicate-slide', label: 'Duplicate Slide', keys: 'mod+d', enabled: hasDeck, run: duplicate },
  { id: 'delete-slide', label: 'Delete Slide', enabled: hasDeck, run: onDeck((doc) => doc.commit(removeSlide(doc.history.present, doc.slide.id), 'Delete Slide', { selected: null })) },
  { id: 'present', label: 'Present', keys: 'mod+shift+enter', enabled: hasDeck, run: () => present(false), dividerBefore: true },
  { id: 'present-start', label: 'Present from the Start', enabled: hasDeck, run: () => present(true) }
]

const INSERT_COMMANDS: OfficeCommand[] = [
  { id: 'insert-text', label: 'Text Box', enabled: hasDeck, run: () => insert('text') },
  { id: 'insert-rectangle', label: 'Rectangle', enabled: hasDeck, run: () => insert('rectangle') },
  { id: 'insert-ellipse', label: 'Ellipse', enabled: hasDeck, run: () => insert('ellipse') },
  { id: 'front', label: 'Bring to Front', enabled: hasSelection, run: onDeck((doc) => doc.selected && doc.commit(arrangeElement(doc.history.present, doc.slide.id, doc.selected, 'front'), 'Bring to Front', { selected: doc.selected })), dividerBefore: true },
  { id: 'back', label: 'Send to Back', enabled: hasSelection, run: onDeck((doc) => doc.selected && doc.commit(arrangeElement(doc.history.present, doc.slide.id, doc.selected, 'back'), 'Send to Back', { selected: doc.selected })) }
]

/** Herald Slides: decks drawn by the Herald Canvas engine, in a Herald window. */
export function SlidesWindow({ payload }: { payload?: Record<string, unknown> }) {
  const menus = useMemo(() => officeMenus({ session: slidesSession, canOpen: false, canSave: false, menus: [{ id: 'slide', label: 'Slide', items: SLIDE_COMMANDS }, { id: 'insert', label: 'Insert', items: INSERT_COMMANDS }] }), [])

  return (
    <>
      <OfficeWindow
        session={slidesSession}
        menus={menus}
        payload={payload}
        noun="presentation"
        canOpen={false}
        start={{ icon: 'slides', blurb: 'Slides with text and shapes, drawn sharp at any size, and presented full screen. PowerPoint files open and save with the next update; Export as PDF keeps a copy now.', newLabel: 'New presentation' }}
        toolbar={(doc: OfficeDocument<Deck>) => <Toolbar key={doc.key} docKey={doc.key} />}
        renderEditor={(doc) => <SlideEditor doc={doc} />}
      />
      <Present />
    </>
  )
}
