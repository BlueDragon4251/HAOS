import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'
import { $prefs, $windowState } from '../../store/backend.ts'

/**
 * Procedural "flowing silk" wallpaper: layered, slowly drifting ribbons on a deep-blue field.
 * Canvas 2D at reduced resolution, ~30fps, paused when the window is blurred or motion is reduced.
 * A user image (prefs.wallpaper) replaces it.
 */
export function Wallpaper() {
  const prefs = useStore($prefs)
  const win = useStore($windowState)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const custom = prefs.wallpaper

  useEffect(() => {
    if (custom) {
      return
    }

    const canvas = canvasRef.current

    if (!canvas) {
      return
    }

    const ctx = canvas.getContext('2d', { alpha: false })

    if (!ctx) {
      return
    }

    const reduce = prefs.reduceMotion || window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let raf = 0
    let last = 0
    let t = Math.random() * 1000
    const scale = 0.5

    const resize = () => {
      canvas.width = Math.max(1, Math.floor(window.innerWidth * scale))
      canvas.height = Math.max(1, Math.floor(window.innerHeight * scale))
    }

    const ribbons = Array.from({ length: 11 }, (_, i) => ({
      y: 0.12 + (i / 11) * 0.8,
      amp: 0.07 + (i % 3) * 0.04,
      freq: 0.9 + (i % 4) * 0.3,
      speed: 0.1 + (i % 5) * 0.03,
      width: 26 + (i % 3) * 30,
      hue: 214 + (i % 4) * 5,
      light: 52 + (i % 3) * 9,
      alpha: 0.3 + (i % 2) * 0.16,
      phase: i * 1.7
    }))

    const draw = (now: number) => {
      const w = canvas.width
      const h = canvas.height
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 0
      last = now
      t += dt

      const base = ctx.createRadialGradient(w * 0.5, h * 0.5, h * 0.05, w * 0.5, h * 0.5, Math.max(w, h) * 0.8)
      base.addColorStop(0, '#1240c8')
      base.addColorStop(0.45, '#0a2a96')
      base.addColorStop(1, '#04113f')
      ctx.fillStyle = base
      ctx.fillRect(0, 0, w, h)

      ctx.lineCap = 'round'
      ctx.globalCompositeOperation = 'lighter'

      const tracePath = (r: (typeof ribbons)[number]) => {
        ctx.beginPath()
        const steps = 56

        for (let s = 0; s <= steps; s++) {
          const x = (s / steps) * w
          const nx = (s / steps) * r.freq * Math.PI * 2
          const y =
            h * r.y +
            Math.sin(nx + t * r.speed + r.phase) * h * r.amp +
            Math.sin(nx * 0.5 - t * r.speed * 0.7 + r.phase * 2) * h * r.amp * 0.6 +
            Math.cos(nx * 1.7 + t * r.speed * 0.4) * h * 0.012

          if (s === 0) {
            ctx.moveTo(x, y)
          } else {
            ctx.lineTo(x, y)
          }
        }
      }

      for (const r of ribbons) {
        // Wide soft body.
        tracePath(r)
        const glow = ctx.createLinearGradient(0, 0, w, 0)
        glow.addColorStop(0, `hsla(${r.hue}, 95%, ${r.light}%, 0)`)
        glow.addColorStop(0.3, `hsla(${r.hue}, 95%, ${r.light + 10}%, ${r.alpha * 0.5})`)
        glow.addColorStop(0.7, `hsla(${r.hue + 6}, 95%, ${r.light + 16}%, ${r.alpha * 0.45})`)
        glow.addColorStop(1, `hsla(${r.hue}, 95%, ${r.light}%, 0)`)
        ctx.strokeStyle = glow
        ctx.lineWidth = r.width * scale * 2.2 * (1 + 0.15 * Math.sin(t * 0.3 + r.phase))
        ctx.stroke()

        // Bright silk highlight.
        tracePath(r)
        const grad = ctx.createLinearGradient(0, 0, w, 0)
        grad.addColorStop(0, `hsla(${r.hue}, 100%, ${r.light + 10}%, 0)`)
        grad.addColorStop(0.35, `hsla(${r.hue}, 100%, ${r.light + 26}%, ${r.alpha})`)
        grad.addColorStop(0.62, `hsla(${r.hue + 8}, 100%, ${r.light + 34}%, ${r.alpha * 1.1})`)
        grad.addColorStop(1, `hsla(${r.hue}, 100%, ${r.light + 10}%, 0)`)
        ctx.strokeStyle = grad
        ctx.lineWidth = r.width * scale * 0.55 * (1 + 0.2 * Math.sin(t * 0.3 + r.phase))
        ctx.stroke()
      }

      ctx.globalCompositeOperation = 'source-over'
      const vignette = ctx.createRadialGradient(w / 2, h / 2, h * 0.35, w / 2, h / 2, Math.max(w, h) * 0.85)
      vignette.addColorStop(0, 'rgba(0,0,0,0)')
      vignette.addColorStop(1, 'rgba(0,4,30,0.4)')
      ctx.fillStyle = vignette
      ctx.fillRect(0, 0, w, h)
    }

    const loop = (now: number) => {
      draw(now)

      if (!reduce) {
        raf = window.setTimeout(() => requestAnimationFrame(loop), 33) as unknown as number
      }
    }

    resize()
    window.addEventListener('resize', resize)
    requestAnimationFrame(loop)

    return () => {
      window.removeEventListener('resize', resize)
      clearTimeout(raf)
    }
    // Repaint when the window regains focus so a paused wallpaper picks up again.
  }, [custom, prefs.reduceMotion, win.focused])

  if (custom) {
    return <div className="absolute inset-0 z-(--z-wallpaper) bg-cover bg-center" style={{ backgroundImage: `url(${JSON.stringify(custom)})` }} />
  }

  return <canvas ref={canvasRef} className="absolute inset-0 z-(--z-wallpaper) h-full w-full" style={{ filter: 'blur(1.5px)' }} aria-hidden="true" />
}
