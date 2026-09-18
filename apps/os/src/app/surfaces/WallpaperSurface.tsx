import { useEffect } from 'react'
import { drawWallpaperFrame } from '../shell/Wallpaper.tsx'

/** A fixed phase that places the ribbons pleasantly: no crossings through the centre, highlights spread out. */
const FRAME_PHASE = 137.5
/** Matches the soft blur the animated wallpaper applies through CSS. */
const FRAME_BLUR_PX = 1.5

/**
 * Panels mode: this window is offscreen and screen-sized. It renders one full-resolution frame of
 * the procedural wallpaper, hands the PNG to main (which feeds swaybg), and main closes the window.
 */
export function WallpaperSurface() {
  useEffect(() => {
    let cancelled = false

    const render = () => {
      const width = Math.max(1, window.innerWidth)
      const height = Math.max(1, window.innerHeight)

      try {
        const scene = document.createElement('canvas')
        scene.width = width
        scene.height = height
        const sceneCtx = scene.getContext('2d', { alpha: false })

        if (!sceneCtx) {
          return
        }

        drawWallpaperFrame(sceneCtx, width, height, FRAME_PHASE, 1)

        // Second pass through a blur filter so the export looks like the on-screen wallpaper.
        const output = document.createElement('canvas')
        output.width = width
        output.height = height
        const outputCtx = output.getContext('2d', { alpha: false })
        let source = scene

        if (outputCtx && 'filter' in outputCtx) {
          outputCtx.fillStyle = '#04113f'
          outputCtx.fillRect(0, 0, width, height)
          outputCtx.filter = `blur(${FRAME_BLUR_PX}px)`
          outputCtx.drawImage(scene, 0, 0)
          outputCtx.filter = 'none'
          source = output
        }

        const dataUrl = source.toDataURL('image/png')

        if (!cancelled) {
          window.hermesOS.shell.wallpaperFrame(dataUrl).catch(() => undefined)
        }
      } catch {
        // Nothing to fall back to here; main keeps the previous render on disk.
      }
    }

    // One rAF so the window has its final size before we read it.
    const raf = requestAnimationFrame(render)

    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
    }
  }, [])

  return <div className="h-full w-full bg-bg" aria-hidden="true" />
}
