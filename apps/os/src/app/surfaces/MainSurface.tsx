import { useStore } from '@nanostores/react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { ShellCommand } from '../../../shared/ipc.ts'
import { afterExit, motion } from '../../lib/motion.ts'
import { $backend } from '../../store/backend.ts'
import { openStoredSession, runSlash, sendPrompt } from '../../store/chat.ts'
import { $notificationsOpen, notify } from '../../store/notifications.ts'
import { openSurface } from '../../store/shell.ts'
import { toggleSidebar } from '../../store/sidebar.ts'
import { $applicationsOpen, $commandBarOpen, toggleCommandBar } from '../../store/surface.ts'
import { ensureMainWindow, openApp, showPage } from '../../store/windows.ts'
import { HERMES_APPS, PAGES, type PageId } from '../apps.ts'
import { BootScreen } from '../shell/BootScreen.tsx'
import { CommandBar } from '../shell/CommandBar.tsx'
import { MainWindow } from '../shell/MainWindow.tsx'
import { NotificationsPanel } from '../shell/NotificationsPanel.tsx'
import { RequestHost } from '../shell/RequestHost.tsx'
import { Toasts } from '../shell/Toasts.tsx'
import { drawWallpaperFrame } from '../shell/Wallpaper.tsx'
import { composePrompt, useShellCommands } from './shell-utils.ts'

const ApplicationsOverlay = lazy(() => import('../apps/ApplicationsOverlay.tsx').then(m => ({ default: m.ApplicationsOverlay })))

const isPageId = (value: string | undefined): value is PageId => PAGES.some(page => page.id === value)

/**
 * Panels mode: the Hermes window. niri tiles it like any other client, so it is just the sidebar and
 * pages filling the window plus the overlays that belong to it. Other surfaces and the `hermes-os` CLI
 * drive it through `ShellCommand`s.
 */
export function MainSurface() {
  const backend = useStore($backend)
  const commandBarOpen = useStore($commandBarOpen)
  const applicationsOpen = useStore($applicationsOpen)

  useEffect(() => {
    ensureMainWindow()
  }, [])

  useShellCommands((command: ShellCommand) => {
    switch (command.type) {
      case 'show-page': {
        const id = command.args?.[0]

        if (isPageId(id)) {
          showPage(id)
        }

        return
      }
      case 'send-prompt': {
        const text = composePrompt(command.text ?? '', command.context, command.attachments)

        if (!text) {
          return
        }

        showPage('hermes')
        openSurface('main')

        // A bare slash command from the palette runs as one; anything with context or files is a prompt.
        if (text.startsWith('/') && !command.context && !command.attachments?.length) {
          void runSlash(text)
        } else {
          void sendPrompt(text)
        }

        return
      }
      case 'open-session': {
        const id = command.args?.[0]

        if (id) {
          showPage('hermes')
          void openStoredSession(id)
        }

        return
      }
      case 'notify': {
        const [title, ...rest] = command.args ?? []

        if (title) {
          notify({ title, body: rest.join(' ') || command.text || undefined })
        }

        return
      }
      case 'notifications':
        $notificationsOpen.set(!$notificationsOpen.get())

        return
      case 'command':
        toggleCommandBar(true)

        return
      case 'applications':
        $applicationsOpen.set(true)

        return
      case 'power':
        // TODO(phase 2): machine-side power actions need an audited IPC; until then, say so.
        notify({ title: 'Power actions arrive in Phase 2', body: command.args?.[0] ? `Requested: ${command.args[0]}` : undefined, level: 'info' })

        return
      case 'payload':
      default:
        return
    }
  })

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey
      const key = event.key.toLowerCase()

      if (meta && key === 'k') {
        event.preventDefault()
        toggleCommandBar()

        return
      }

      if (meta && event.shiftKey && key === 'a') {
        event.preventDefault()
        $applicationsOpen.set(!$applicationsOpen.get())

        return
      }

      if (meta && event.key === '\\') {
        event.preventDefault()
        toggleSidebar()

        return
      }

      if (meta && !event.shiftKey && !event.altKey) {
        const target = HERMES_APPS.find(a => a.shortcut === event.key)

        if (target) {
          event.preventDefault()
          openApp(target.id)

          return
        }
      }

      if (event.key === 'Escape') {
        if ($commandBarOpen.get()) {
          toggleCommandBar(false)
        } else if ($applicationsOpen.get()) {
          $applicationsOpen.set(false)
        }
      }
    }

    window.addEventListener('keydown', onKey)

    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const bootOnly = backend.phase === 'idle' || backend.phase === 'resolving' || (backend.phase === 'starting' && backend.attempt === 0) || backend.phase === 'failed'
  const bootVisible = useExitTransition(bootOnly, motion.slow + 120)

  return (
    <div className="h-full w-full bg-bg text-fg">
      <div className="relative h-full w-full overflow-hidden bg-bg">
        <StillWallpaper />
        <div className="absolute inset-0 z-(--z-windows)">
          <MainWindow />
        </div>
        <RequestHost />
        <Toasts />
        <NotificationsPanel />
        {applicationsOpen && (
          <Suspense fallback={null}>
            <ApplicationsOverlay />
          </Suspense>
        )}
        {commandBarOpen && <CommandBar />}
      </div>
      {bootVisible && <BootScreen state={backend} leaving={!bootOnly} />}
    </div>
  )
}

/** One still frame of the wallpaper behind the sidebar and page so the glass has something to sit on. */
function StillWallpaper() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current

    if (!canvas) {
      return
    }

    const ctx = canvas.getContext('2d', { alpha: false })

    if (!ctx) {
      return
    }

    const scale = 0.5
    const draw = () => {
      canvas.width = Math.max(1, Math.floor(window.innerWidth * scale))
      canvas.height = Math.max(1, Math.floor(window.innerHeight * scale))
      drawWallpaperFrame(ctx, canvas.width, canvas.height, 137.5, scale)
    }

    draw()
    window.addEventListener('resize', draw)

    return () => window.removeEventListener('resize', draw)
  }, [])

  return <canvas ref={canvasRef} className="absolute inset-0 z-(--z-wallpaper) h-full w-full opacity-70" style={{ filter: 'blur(1.5px)' }} aria-hidden="true" />
}

/** Keep `true` for `ms` after `open` turns false so an exit animation can play (skipped under reduced motion). */
function useExitTransition(open: boolean, ms: number): boolean {
  const [visible, setVisible] = useState(open)

  useEffect(() => {
    if (open) {
      setVisible(true)

      return
    }

    let cancelled = false
    afterExit(() => {
      if (!cancelled) {
        setVisible(false)
      }
    }, ms)

    return () => {
      cancelled = true
    }
  }, [open, ms])

  return visible
}
