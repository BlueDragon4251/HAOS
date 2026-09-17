import { useStore } from '@nanostores/react'
import { useEffect } from 'react'
import { $backend } from '../store/backend.ts'
import { $commandBarOpen, $surface, showSurface, toggleCommandBar } from '../store/surface.ts'
import { BootScreen } from './shell/BootScreen.tsx'
import { Desktop } from './shell/Desktop.tsx'
import { SURFACES } from './surfaces.ts'

export function App() {
  const backend = useStore($backend)
  const surface = useStore($surface)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey

      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        toggleCommandBar()

        return
      }

      if (meta && !event.shiftKey && !event.altKey) {
        const target = SURFACES.find(s => s.shortcut === event.key)

        if (target) {
          event.preventDefault()
          showSurface(target.id)
        }
      }

      if (event.key === 'Escape' && $commandBarOpen.get()) {
        toggleCommandBar(false)
      }
    }

    window.addEventListener('keydown', onKey)

    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // The desktop mounts as soon as the shell can be useful; the boot screen only owns the
  // genuinely unusable states (first resolve/start, terminal failure).
  const bootOnly = backend.phase === 'idle' || backend.phase === 'resolving' || (backend.phase === 'starting' && backend.attempt === 0) || backend.phase === 'failed'

  return (
    <div className="h-full w-full bg-bg text-fg">
      <Desktop surface={surface} />
      {bootOnly && <BootScreen state={backend} />}
    </div>
  )
}
