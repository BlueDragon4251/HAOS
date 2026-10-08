import { useStore } from '@nanostores/react'
import { useEffect, useLayoutEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { SLIDE_SIZE } from './deck.ts'
import { SlideCanvas } from './SlideEditor.tsx'
import { $presenting, decks } from './store.ts'

/** Start presenting: called from the click or key that asks, since the system grants full screen only then. */
export function startPresenting(key: string, index: number): void {
  $presenting.set({ key, index })

  // Herald's own window usually fills the screen already; leaving full screen must not take it out of that.
  if (window.outerWidth < screen.width || window.outerHeight < screen.height) {
    document.documentElement.requestFullscreen?.().catch(() => {})
  }
}

/**
 * The deck full screen, a slide at a time: arrows, Space and clicks move on, Escape ends. It is
 * drawn on the page itself rather than in the window, whose frame would hold it to its own size.
 */
export function Present() {
  const presenting = useStore($presenting)
  const doc = presenting ? decks.get(presenting.key) : undefined
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight })

  useLayoutEffect(() => {
    const onResize = () => setSize({ width: window.innerWidth, height: window.innerHeight })
    window.addEventListener('resize', onResize)

    return () => window.removeEventListener('resize', onResize)
  }, [])

  const showing = Boolean(presenting)
  useEffect(() => {
    if (!showing) {
      return
    }

    return () => {
      if (document.fullscreenElement) {
        void document.exitFullscreen().catch(() => {})
      }
    }
  }, [showing])

  useEffect(() => {
    if (!presenting || !doc) {
      return
    }

    const count = doc.deck.slides.length
    const go = (index: number) => $presenting.set({ ...presenting, index: Math.max(0, Math.min(count - 1, index)) })
    const onKey = (event: KeyboardEvent) => {
      const forward = ['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter', 'n'].includes(event.key)
      const back = ['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace', 'p'].includes(event.key)

      if (event.key === 'Escape') {
        $presenting.set(null)
      } else if (forward) {
        go(presenting.index + 1)
      } else if (back) {
        go(presenting.index - 1)
      } else if (event.key === 'Home') {
        go(0)
      } else if (event.key === 'End') {
        go(count - 1)
      } else {
        return
      }

      event.preventDefault()
      event.stopPropagation()
    }
    window.addEventListener('keydown', onKey, true)

    return () => window.removeEventListener('keydown', onKey, true)
  }, [presenting, doc])

  if (!presenting || !doc) {
    return null
  }

  const slide = doc.deck.slides[presenting.index] ?? doc.deck.slides[0]
  const width = Math.min(size.width, (size.height * SLIDE_SIZE.width) / SLIDE_SIZE.height)

  return createPortal(
    <div
      role="dialog"
      aria-label={`Presenting slide ${presenting.index + 1} of ${doc.deck.slides.length}`}
      className="fixed inset-0 z-[2147483000] flex cursor-none items-center justify-center bg-black"
      onClick={() => $presenting.set({ ...presenting, index: Math.min(doc.deck.slides.length - 1, presenting.index + 1) })}
      onContextMenu={(event) => {
        event.preventDefault()
        $presenting.set({ ...presenting, index: Math.max(0, presenting.index - 1) })
      }}
    >
      <SlideCanvas deck={doc.deck} slide={slide} width={width} />
    </div>,
    document.body
  )
}
