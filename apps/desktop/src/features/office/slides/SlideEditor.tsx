import { IconPlus } from '@tabler/icons-react'
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { cn } from '../../../lib/cn.ts'
import { matches } from '../../../lib/shortcuts.ts'
import type { EditorHandle, OfficeDocument } from '../types.ts'
import { addSlide, type Deck, removeElement, setNotes, type Slide, SLIDE_SIZE, type SlideElement, type TextBox, updateElement } from './deck.ts'
import { SlidesDocument } from './model.ts'
import { paint, renderSlide } from './render.ts'
import { decks, slidesSession } from './store.ts'

export function useDeck(doc: SlidesDocument | undefined): number {
  return useSyncExternalStore(
    (listener) => (doc ? doc.subscribe(listener) : () => {}),
    () => doc?.revision ?? -1
  )
}

/** A slide drawn into a canvas whenever it or its size changes; a render that finishes after a newer one started is dropped. */
export function SlideCanvas({ deck, slide, width, without, className }: { deck: Deck; slide: Slide; width: number; without?: string | null; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const turn = useRef(0)

  useEffect(() => {
    const canvas = ref.current

    if (!canvas || width <= 0) {
      return
    }

    const mine = ++turn.current
    const frame = requestAnimationFrame(() => {
      renderSlide(deck, slide, (width * devicePixelRatio) / SLIDE_SIZE.width, { without })
        .then((raster) => mine === turn.current && paint(canvas, raster))
        .catch(() => {})
    })

    return () => cancelAnimationFrame(frame)
  }, [deck.theme, slide, width, without])

  return <canvas ref={ref} aria-hidden="true" className={className} style={{ width, height: (width * SLIDE_SIZE.height) / SLIDE_SIZE.width }} />
}

function SlideStrip({ doc }: { doc: SlidesDocument }) {
  useDeck(doc)
  const deck = doc.deck

  return (
    <div className="flex w-48 shrink-0 flex-col gap-3 overflow-y-auto border-r border-line p-3" role="listbox" aria-label="Slides">
      {deck.slides.map((slide, index) => (
        <button
          key={slide.id}
          type="button"
          role="option"
          aria-selected={slide.id === doc.slide.id}
          aria-label={`Slide ${index + 1}`}
          onClick={() => doc.goTo(slide.id)}
          className="flex items-start gap-2 text-left"
        >
          <span className="w-4 shrink-0 pt-0.5 text-right text-[11px] text-fg-3 tabular-nums">{index + 1}</span>
          <span className={cn('overflow-hidden rounded-[3px] ring-2 ring-offset-0', slide.id === doc.slide.id ? 'ring-accent' : 'ring-transparent hover:ring-line-strong')}>
            <SlideCanvas deck={deck} slide={slide} width={144} className="block" />
          </span>
        </button>
      ))}
      <button
        type="button"
        onClick={() => {
          const { deck: next, slideId } = addSlide(doc.history.present, 'title-body', doc.slide.id)
          doc.commit(next, 'New Slide', { slideId, selected: null })
        }}
        className="ml-6 flex h-[81px] w-[144px] shrink-0 items-center justify-center rounded-[3px] border border-dashed border-line text-fg-3 hover:border-line-strong hover:text-fg"
        aria-label="New slide"
      >
        <IconPlus size={18} />
      </button>
    </div>
  )
}

type Edge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'
const EDGES: Edge[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']
const HANDLE_PLACE: Record<Edge, string> = {
  nw: '-left-1 -top-1 cursor-nwse-resize',
  n: 'left-1/2 -top-1 -translate-x-1/2 cursor-ns-resize',
  ne: '-right-1 -top-1 cursor-nesw-resize',
  e: '-right-1 top-1/2 -translate-y-1/2 cursor-ew-resize',
  se: '-right-1 -bottom-1 cursor-nwse-resize',
  s: 'left-1/2 -bottom-1 -translate-x-1/2 cursor-ns-resize',
  sw: '-left-1 -bottom-1 cursor-nesw-resize',
  w: '-left-1 top-1/2 -translate-y-1/2 cursor-ew-resize'
}

/** Follow a drag from a pointer-down: `move` gets the distance in points; the deck it previews becomes one step on release. */
function drag(event: React.PointerEvent, fit: number, doc: SlidesDocument, label: string, move: (dx: number, dy: number) => Deck, selected: string): void {
  const target = event.currentTarget as HTMLElement
  const startX = event.clientX
  const startY = event.clientY
  let moved = false
  target.setPointerCapture(event.pointerId)

  const onMove = (pointer: PointerEvent) => {
    if (!moved && Math.hypot(pointer.clientX - startX, pointer.clientY - startY) < 3) {
      return
    }

    moved = true
    doc.show(move((pointer.clientX - startX) / fit, (pointer.clientY - startY) / fit))
  }
  const onUp = () => {
    target.removeEventListener('pointermove', onMove)

    if (moved && doc.preview) {
      doc.commit(doc.preview, label, { selected })
    } else {
      doc.show(null)
    }
  }

  target.addEventListener('pointermove', onMove)
  target.addEventListener('pointerup', onUp, { once: true })
  target.addEventListener('pointercancel', onUp, { once: true })
}

function ElementBox({ doc, element, fit }: { doc: SlidesDocument; element: SlideElement; fit: number }) {
  const selected = doc.selected === element.id
  const placeholder = element.kind === 'text' && !element.text.trim() ? element.placeholder : undefined
  const slideId = doc.slide.id

  const onPointerDown = (event: React.PointerEvent) => {
    if (event.button !== 0) {
      return
    }

    event.stopPropagation()

    if (doc.editing === element.id) {
      return
    }

    doc.select(element.id)
    const base = doc.history.present
    drag(event, fit, doc, 'Move', (dx, dy) => updateElement(base, slideId, element.id, { x: element.x + dx, y: element.y + dy }), element.id)
  }

  const onResize = (edge: Edge) => (event: React.PointerEvent) => {
    event.stopPropagation()
    const base = doc.history.present
    drag(
      event,
      fit,
      doc,
      'Resize',
      (dx, dy) => {
        const box = { x: element.x, y: element.y, width: element.width, height: element.height }

        if (edge.includes('e')) box.width += dx
        if (edge.includes('s')) box.height += dy
        if (edge.includes('w')) {
          box.x += dx
          box.width -= dx
        }
        if (edge.includes('n')) {
          box.y += dy
          box.height -= dy
        }

        return updateElement(base, slideId, element.id, box)
      },
      element.id
    )
  }

  return (
    <div
      data-element={element.id}
      onPointerDown={onPointerDown}
      onDoubleClick={() => element.kind === 'text' && doc.select(element.id, true)}
      className={cn('absolute cursor-move', selected ? 'outline-2 outline-accent' : 'hover:outline hover:outline-accent/50', placeholder && !selected && 'outline-1 outline-dashed outline-black/25')}
      style={{ left: element.x * fit, top: element.y * fit, width: element.width * fit, height: element.height * fit }}
    >
      {placeholder && doc.editing !== element.id && (
        // Top-anchored, as the text the box gets is drawn.
        <div className="pointer-events-none h-full w-full overflow-hidden leading-[1.2] text-black/35" style={{ fontSize: (element as TextBox).size * fit, textAlign: (element as TextBox).align }}>
          {placeholder}
        </div>
      )}
      {selected &&
        doc.editing !== element.id &&
        EDGES.map((edge) => <span key={edge} onPointerDown={onResize(edge)} className={cn('absolute size-2.5 rounded-[2px] border border-accent bg-white', HANDLE_PLACE[edge])} />)}
    </div>
  )
}

/** Typing into a text box: a field over the box, in its font; the canvas leaves the box out meanwhile. */
function TextEditing({ doc, element, fit, font }: { doc: SlidesDocument; element: TextBox; fit: number; font: string }) {
  const [text, setText] = useState(element.text)
  const field = useRef<HTMLTextAreaElement>(null)
  const done = useRef(false)

  useEffect(() => {
    field.current?.focus()
    field.current?.select()
  }, [])

  const finish = () => {
    if (done.current) {
      return
    }

    done.current = true
    const slideId = doc.slide.id

    if (text !== element.text) {
      doc.commit(updateElement(doc.history.present, slideId, element.id, { text }), 'Typing', { selected: element.id })
    }

    doc.select(element.id)
  }

  return (
    <textarea
      ref={field}
      value={text}
      aria-label="Text"
      spellCheck
      onChange={(event) => setText(event.target.value)}
      onBlur={finish}
      onPointerDown={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation()

        if (event.key === 'Escape') {
          event.currentTarget.blur()
        }
      }}
      className="absolute resize-none overflow-hidden border-0 bg-transparent p-0 outline-2 outline-accent outline-dashed"
      style={{
        left: element.x * fit,
        top: element.y * fit,
        width: element.width * fit,
        height: element.height * fit,
        fontFamily: `"${font}", system-ui, sans-serif`,
        fontSize: element.size * fit,
        fontWeight: element.bold ? 700 : 400,
        fontStyle: element.italic ? 'italic' : 'normal',
        lineHeight: 1.2,
        color: element.color,
        textAlign: element.align,
        caretColor: element.color
      }}
    />
  )
}

function Stage({ doc }: { doc: SlidesDocument }) {
  useDeck(doc)
  const area = useRef<HTMLDivElement>(null)
  const [fit, setFit] = useState(0)

  useLayoutEffect(() => {
    const element = area.current

    if (!element) {
      return
    }

    const measure = () => setFit(Math.max(0.05, Math.min((element.clientWidth - 48) / SLIDE_SIZE.width, (element.clientHeight - 48) / SLIDE_SIZE.height)))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)

    return () => observer.disconnect()
  }, [])

  const deck = doc.deck
  const slide = doc.slide
  const editing = slide.elements.find((element): element is TextBox => element.id === doc.editing && element.kind === 'text')

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) {
      return
    }

    const selected = slide.elements.find((element) => element.id === doc.selected)
    const step = event.shiftKey ? 10 : 1
    const arrows: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }

    if (matches(event, 'mod+z')) {
      doc.undo()
    } else if (matches(event, 'mod+shift+z')) {
      doc.redo()
    } else if (selected && (event.key === 'Backspace' || event.key === 'Delete')) {
      doc.commit(removeElement(doc.history.present, slide.id, selected.id), 'Delete', { selected: null })
    } else if (selected && arrows[event.key] && !event.metaKey && !event.ctrlKey) {
      const [dx, dy] = arrows[event.key]
      doc.commit(updateElement(doc.history.present, slide.id, selected.id, { x: selected.x + dx, y: selected.y + dy }), 'Nudge', { selected: selected.id })
    } else if (selected?.kind === 'text' && event.key === 'Enter') {
      doc.select(selected.id, true)
    } else if (event.key === 'Escape' && doc.selected) {
      doc.select(null)
    } else {
      return
    }

    event.preventDefault()
    event.stopPropagation()
  }

  return (
    <div ref={area} tabIndex={0} onKeyDown={onKeyDown} onPointerDown={(event) => event.target === event.currentTarget && doc.select(null)} className="relative flex min-h-0 flex-1 items-center justify-center outline-none" aria-label={`Slide ${doc.index + 1}`}>
      {fit > 0 && (
        <div className="relative shadow-[0_10px_40px_rgba(0,8,50,.55)]" style={{ width: SLIDE_SIZE.width * fit, height: SLIDE_SIZE.height * fit }} onPointerDown={(event) => event.target === event.currentTarget && doc.select(null)}>
          <SlideCanvas deck={deck} slide={slide} width={SLIDE_SIZE.width * fit} without={doc.editing} className="pointer-events-none absolute inset-0" />
          <div className="absolute inset-0" onPointerDown={(event) => event.target === event.currentTarget && doc.select(null)}>
            {slide.elements.map((element) => (
              <ElementBox key={element.id} doc={doc} element={element} fit={fit} />
            ))}
          </div>
          {editing && <TextEditing key={editing.id} doc={doc} element={editing} fit={fit} font={deck.theme.font} />}
        </div>
      )}
    </div>
  )
}

function Notes({ doc }: { doc: SlidesDocument }) {
  useDeck(doc)
  const slide = doc.slide
  const [text, setText] = useState(slide.notes)

  useEffect(() => setText(slide.notes), [slide.id, slide.notes])

  return (
    <textarea
      value={text}
      onChange={(event) => setText(event.target.value)}
      onBlur={() => text !== slide.notes && doc.commit(setNotes(doc.history.present, slide.id, text), 'Speaker Notes')}
      onKeyDown={(event) => event.stopPropagation()}
      placeholder="Speaker notes"
      aria-label="Speaker notes"
      className="glass-input mx-6 mb-3 h-16 shrink-0 resize-none rounded-lg px-3 py-2 text-[12.5px] text-fg outline-none placeholder:text-fg-4"
    />
  )
}

/** One deck: its slides down the side, the slide in front, and its notes. */
export function SlideEditor({ doc: officeDoc }: { doc: OfficeDocument<Deck> }) {
  const [doc] = useState(() => new SlidesDocument(officeDoc.initial, () => slidesSession.changed(officeDoc)))

  useEffect(() => {
    const handle: EditorHandle<Deck> = {
      snapshot: () => doc.history.present,
      load: (deck) => doc.reset(deck),
      undo: () => void doc.undo(),
      redo: () => void doc.redo(),
      status: () => `Slide ${doc.index + 1} of ${doc.deck.slides.length}`,
      detail: () => `slide ${doc.index + 1} of ${doc.deck.slides.length}`,
      dispose: () => decks.delete(officeDoc.key)
    }
    decks.set(officeDoc.key, doc)
    slidesSession.attach(officeDoc, handle)
    // The status bar shows the slide in front.
    const off = doc.subscribe(() => slidesSession.refresh(officeDoc))

    return () => {
      off()
      // The deck outlives its view (a closed window keeps it until Herald quits).
      officeDoc.initial = doc.history.present

      if (officeDoc.editor === handle) {
        slidesSession.attach(officeDoc, null)
      }

      decks.delete(officeDoc.key)
    }
  }, [officeDoc.key])

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <SlideStrip doc={doc} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Stage doc={doc} />
        <Notes doc={doc} />
      </div>
    </div>
  )
}
