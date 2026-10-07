import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'
import type { Vec2 } from '../../../shared/canvas/comp-format.ts'
import { cn } from '../../lib/cn.ts'
import { layerAt, movedState } from './actions.ts'
import type { CanvasDocument } from './engine/document.ts'
import { apply, corners } from './engine/geometry.ts'
import { docToScreen, fitView, type Look, ScreenRenderer, type View, zoomAt } from './engine/gpu/view.ts'
import { $autoSelect, $spaceHeld, $tool } from './tools.ts'
import { $pointer, $views, setView, viewOf, viewport, zoomStep } from './view-state.ts'

const LOOK: Look = { workspace: null, checkerLight: [0.4, 0.4, 0.42], checkerDark: [0.31, 0.31, 0.33] }
const OUTLINE = '#4da3ff'

interface Drag {
  move: (event: PointerEvent) => void
  up?: () => void
}

/**
 * The document on screen. Scroll to pan, pinch or ⌘-scroll to zoom, Space or the middle button to
 * drag the view; the Move tool drags the picked layers.
 */
export function Viewport({ doc }: { doc: CanvasDocument }) {
  const host = useRef<HTMLDivElement>(null)
  const glCanvas = useRef<HTMLCanvasElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const renderer = useRef<ScreenRenderer | null>(null)
  const docRef = useRef(doc)
  const frame = useRef(0)
  const drag = useRef<Drag | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const views = useStore($views)
  const tool = useStore($tool)
  const space = useStore($spaceHeld)
  docRef.current = doc

  const paint = () => {
    frame.current = 0
    const current = docRef.current
    const view = viewOf(current)
    const dpr = window.devicePixelRatio || 1

    try {
      renderer.current?.draw(current, view, LOOK, dpr)
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error))
    }

    drawOverlay(overlay.current, current, view, dpr)
  }
  const paintRef = useRef(paint)
  paintRef.current = paint
  const schedule = useRef(() => {
    if (!frame.current) {
      frame.current = requestAnimationFrame(() => paintRef.current())
    }
  }).current

  // The GL context, sized to the viewport in device pixels.
  useEffect(() => {
    const canvas = glCanvas.current!
    const element = host.current!

    try {
      renderer.current = new ScreenRenderer(canvas)
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error))
    }

    const lost = (event: Event) => event.preventDefault()
    const restored = () => {
      try {
        renderer.current = new ScreenRenderer(canvas)
        schedule()
      } catch (error) {
        setFailure(error instanceof Error ? error.message : String(error))
      }
    }
    const resize = () => {
      const rect = element.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      viewport.width = rect.width
      viewport.height = rect.height

      for (const target of [canvas, overlay.current!]) {
        target.width = Math.max(1, Math.round(rect.width * dpr))
        target.height = Math.max(1, Math.round(rect.height * dpr))
      }

      schedule()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    resize()
    canvas.addEventListener('webglcontextlost', lost)
    canvas.addEventListener('webglcontextrestored', restored)

    return () => {
      observer.disconnect()
      canvas.removeEventListener('webglcontextlost', lost)
      canvas.removeEventListener('webglcontextrestored', restored)
      cancelAnimationFrame(frame.current)
      frame.current = 0
      renderer.current?.dispose()
      renderer.current = null
    }
  }, [schedule])

  // A document seen for the first time opens fitted, never past 100%.
  useEffect(() => {
    if (!$views.get()[doc.key]) {
      setView(doc, fitView(viewport.width, viewport.height, doc.state.width, doc.state.height, 1))
    }

    schedule()

    return doc.subscribe(schedule)
  }, [doc, schedule])

  useEffect(schedule, [views, tool, schedule])

  // Wheel: scroll pans, pinch (ctrl) or ⌘-scroll zooms. Not passive, so the page never scrolls.
  useEffect(() => {
    const element = host.current!
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const current = docRef.current
      const view = viewOf(current)
      const rect = element.getBoundingClientRect()
      const unit = event.deltaMode === 1 ? 16 : 1

      if (event.ctrlKey || event.metaKey) {
        // A pinch sends small deltas with ctrl held; a wheel with ⌘ sends large ones.
        const factor = Math.exp(-event.deltaY * unit * (event.metaKey ? 0.0025 : 0.01))
        setView(current, zoomAt(view, factor, event.clientX - rect.left, event.clientY - rect.top))
      } else {
        setView(current, { ...view, panX: view.panX - event.deltaX * unit, panY: view.panY - event.deltaY * unit })
      }
    }
    element.addEventListener('wheel', onWheel, { passive: false })

    return () => element.removeEventListener('wheel', onWheel)
  }, [])

  const locate = (event: { clientX: number; clientY: number }) => {
    const rect = host.current!.getBoundingClientRect()
    const view = viewOf(docRef.current)
    const sx = event.clientX - rect.left
    const sy = event.clientY - rect.top

    return { sx, sy, x: (sx - view.panX) / view.zoom, y: (sy - view.panY) / view.zoom }
  }

  const begin = (next: Drag, event: React.PointerEvent) => {
    drag.current = next
    setDragging(true)
    const target = event.currentTarget as HTMLElement
    target.setPointerCapture(event.pointerId)
    const move = (e: PointerEvent) => drag.current?.move(e)
    const up = () => {
      target.removeEventListener('pointermove', move)
      target.removeEventListener('pointerup', up)
      target.removeEventListener('pointercancel', up)
      drag.current?.up?.()
      drag.current = null
      setDragging(false)
    }
    target.addEventListener('pointermove', move)
    target.addEventListener('pointerup', up)
    target.addEventListener('pointercancel', up)
  }

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    ;(event.currentTarget.closest('[data-canvas-root]') as HTMLElement | null)?.focus({ preventScroll: true })
    const current = docRef.current
    const point = locate(event)

    if (event.button === 1 || $spaceHeld.get() || $tool.get() === 'hand') {
      event.preventDefault()
      const start = viewOf(current)
      begin({ move: (e) => setView(current, { ...start, panX: start.panX + e.clientX - event.clientX, panY: start.panY + e.clientY - event.clientY }) }, event)

      return
    }

    if (event.button !== 0) {
      return
    }

    if ($tool.get() === 'zoom') {
      zoomStep(current, event.altKey ? -1 : 1, point.sx, point.sy)

      return
    }

    if ($autoSelect.get() !== (event.metaKey || event.ctrlKey)) {
      const hit = layerAt(current, point.x, point.y)

      if (hit) {
        current.select(hit.id, event.shiftKey)
      }
    }

    const ids = current.picked.map((layer) => layer.id)

    if (!ids.length) {
      return
    }

    const before = current.state
    let offset: Vec2 = [0, 0]
    begin(
      {
        move: (e) => {
          const at = locate(e)
          let dx = Math.round(at.x - point.x)
          let dy = Math.round(at.y - point.y)

          if (e.shiftKey) {
            if (Math.abs(dx) > Math.abs(dy)) {
              dy = 0
            } else {
              dx = 0
            }
          }

          if (dx !== offset[0] || dy !== offset[1]) {
            offset = [dx, dy]
            current.preview(dx || dy ? movedState(before, ids, dx, dy) : before)
          }
        },
        up: () => {
          if (offset[0] || offset[1]) {
            current.commitFrom('Move', before)
          }
        }
      },
      event
    )
  }

  const onPointerMove = (event: React.PointerEvent) => {
    const { x, y } = locate(event)
    const { width, height } = docRef.current.state
    $pointer.set(x >= 0 && y >= 0 && x < width && y < height ? { x: Math.floor(x), y: Math.floor(y) } : null)
  }

  const cursor = space || tool === 'hand' ? (dragging ? 'cursor-grabbing' : 'cursor-grab') : tool === 'zoom' ? 'cursor-zoom-in' : 'cursor-default'

  return (
    <div
      ref={host}
      className={cn('relative min-h-0 min-w-0 flex-1 overflow-hidden touch-none select-none', cursor)}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerLeave={() => $pointer.set(null)}
      onAuxClick={(event) => event.preventDefault()}
    >
      <canvas ref={glCanvas} className="absolute inset-0 size-full" />
      <canvas ref={overlay} className="pointer-events-none absolute inset-0 size-full" />
      {failure && (
        <div className="absolute inset-0 flex items-center justify-center p-8 text-center text-[13px] text-fg-3">
          <div className="max-w-sm">Herald Canvas could not draw this document: {failure}</div>
        </div>
      )}
    </div>
  )
}

function drawOverlay(canvas: HTMLCanvasElement | null, doc: CanvasDocument, view: View, dpr: number): void {
  const context = canvas?.getContext('2d')

  if (!canvas || !context) {
    return
  }

  context.setTransform(1, 0, 0, 1, 0, 0)
  context.clearRect(0, 0, canvas.width, canvas.height)
  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  const toScreen = docToScreen(view)
  const { width, height } = doc.state

  // The page edge, so a white document still reads against a light window.
  context.strokeStyle = 'rgba(255, 255, 255, 0.14)'
  context.lineWidth = 1
  context.strokeRect(Math.round(view.panX) - 0.5, Math.round(view.panY) - 0.5, Math.round(width * view.zoom) + 1, Math.round(height * view.zoom) + 1)

  context.strokeStyle = 'rgba(0, 220, 255, 0.85)'

  for (const guide of doc.state.guides) {
    context.beginPath()

    if (guide.axis === 'vertical') {
      const x = Math.round(view.panX + guide.position * view.zoom) + 0.5
      context.moveTo(x, 0)
      context.lineTo(x, canvas.height / dpr)
    } else {
      const y = Math.round(view.panY + guide.position * view.zoom) + 0.5
      context.moveTo(0, y)
      context.lineTo(canvas.width / dpr, y)
    }

    context.stroke()
  }

  if ($tool.get() !== 'move') {
    return
  }

  context.strokeStyle = OUTLINE

  for (const layer of doc.picked) {
    if (layer.isGroup) {
      continue
    }

    const points = corners(layer.transform).map((point) => apply(toScreen, point))
    context.beginPath()
    points.forEach(([x, y], i) => (i ? context.lineTo(x, y) : context.moveTo(x, y)))
    context.closePath()
    context.stroke()
  }
}
