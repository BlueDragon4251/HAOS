import { useStore } from '@nanostores/react'
import { useEffect } from 'react'
import { $backend } from '../store/backend.ts'
import { $applicationsOpen, $commandBarOpen, toggleCommandBar } from '../store/surface.ts'
import { $focusedWindowId, closeWindow, MAIN_WINDOW_ID, minimizeWindow, openApp } from '../store/windows.ts'
import { HERMES_APPS } from './apps.ts'
import { BootScreen } from './shell/BootScreen.tsx'
import { Desktop } from './shell/Desktop.tsx'

export function App() {
  const backend = useStore($backend)

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

      if (meta && !event.shiftKey && !event.altKey) {
        const target = HERMES_APPS.find(a => a.shortcut === event.key)

        if (target) {
          event.preventDefault()
          openApp(target.id)

          return
        }

        const focused = $focusedWindowId.get()

        if (key === 'w' && focused && focused !== MAIN_WINDOW_ID) {
          event.preventDefault()
          closeWindow(focused)
        } else if (key === 'm' && focused) {
          event.preventDefault()
          minimizeWindow(focused)
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

  return (
    <div className="h-full w-full bg-bg text-fg">
      <Desktop />
      {bootOnly && <BootScreen state={backend} />}
    </div>
  )
}
