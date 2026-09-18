import { useStore } from '@nanostores/react'
import { lazy, Suspense, useEffect } from 'react'
import { $applicationsOpen, $commandBarOpen } from '../../store/surface.ts'
import { $prefs } from '../../store/backend.ts'
import { $windows, dockAutoHides, ensureMainWindow, MAIN_WINDOW_ID, type OSWindow, relayoutOnResize } from '../../store/windows.ts'
import { Window } from '../wm/Window.tsx'
import { CommandBar } from './CommandBar.tsx'
import { Dock } from './Dock.tsx'
import { MainWindow } from './MainWindow.tsx'
import { MenuBar } from './MenuBar.tsx'
import { NotificationsPanel } from './NotificationsPanel.tsx'
import { RequestHost } from './RequestHost.tsx'
import { Toasts } from './Toasts.tsx'
import { Wallpaper } from './Wallpaper.tsx'

const TerminalSurface = lazy(() => import('../terminal/TerminalSurface.tsx').then(m => ({ default: m.TerminalSurface })))
const SystemSurface = lazy(() => import('../system/SystemSurface.tsx').then(m => ({ default: m.SystemSurface })))
const ChatPopout = lazy(() => import('../hermes/ChatPopout.tsx').then(m => ({ default: m.ChatPopout })))
const ApplicationsOverlay = lazy(() => import('../apps/ApplicationsOverlay.tsx').then(m => ({ default: m.ApplicationsOverlay })))

function FloatingContent({ win }: { win: OSWindow }) {
  switch (win.appId) {
    case 'terminal':
      return <TerminalSurface />
    case 'system':
      return <SystemSurface />
    case 'chat-popout':
      return <ChatPopout sessionId={typeof win.payload?.sessionId === 'string' ? win.payload.sessionId : undefined} />
    default:
      return null
  }
}

/** The desktop: wallpaper, menu bar, windows, dock, overlays. */
export function Desktop() {
  const windows = useStore($windows)
  const commandBarOpen = useStore($commandBarOpen)
  const applicationsOpen = useStore($applicationsOpen)

  useEffect(() => {
    ensureMainWindow()
    const onResize = () => relayoutOnResize()
    window.addEventListener('resize', onResize)
    // Toggling Dock auto-hide changes the desktop area, so windows re-flow like on a resize.
    let lastAutoHide = dockAutoHides()
    const offPrefs = $prefs.subscribe(() => {
      const next = dockAutoHides()

      if (next !== lastAutoHide) {
        lastAutoHide = next
        relayoutOnResize()
      }
    })

    return () => {
      window.removeEventListener('resize', onResize)
      offPrefs()
    }
  }, [])

  return (
    <div className="relative h-full w-full overflow-hidden bg-bg">
      <Wallpaper />
      <MenuBar />
      <div className="absolute inset-0 z-(--z-windows)">
        {Object.values(windows).map(win =>
          win.id === MAIN_WINDOW_ID ? (
            <Window key={win.id} win={win} chrome={false}>
              <MainWindow />
            </Window>
          ) : (
            <Window key={win.id} win={win}>
              <Suspense fallback={<div className="shimmer h-full w-full" />}>
                <FloatingContent win={win} />
              </Suspense>
            </Window>
          )
        )}
      </div>
      <Dock />
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
  )
}
