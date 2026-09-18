import { useStore } from '@nanostores/react'
import { IconArrowRight, IconMessage, IconSlash } from '@tabler/icons-react'
import { Command } from 'cmdk'
import { useMemo, useState } from 'react'
import { AppGlyph, HermesAvatar } from '../../components/app-icon.tsx'
import { Kbd } from '../../components/ui/primitives.tsx'
import { cn } from '../../lib/cn.ts'
import { openStoredSession, runSlash, sendPrompt } from '../../store/chat.ts'
import { useNativeApps } from '../../store/native-apps.ts'
import { $sessions } from '../../store/sessions.ts'
import { openSurface, relayToMain } from '../../store/shell.ts'
import { $applicationsOpen, $commandBarOpen, toggleCommandBar } from '../../store/surface.ts'
import { openApp, showPage } from '../../store/windows.ts'
import { HERMES_APPS } from '../apps.ts'
import { useSlashCatalog } from '../chat/use-slash-catalog.ts'

/**
 * The global command bar (Cmd+K): type to talk to Hermes, or jump to a page, session, app or slash
 * command. Enter on free text sends it to Hermes and opens the Hermes page.
 */
export function CommandBar() {
  const open = useStore($commandBarOpen)

  if (!open) {
    return null
  }

  const close = () => toggleCommandBar(false)

  return (
    <div className="absolute inset-0 z-(--z-command) flex items-start justify-center bg-black/35 pt-[14vh] backdrop-blur-[2px] animate-fade-in" onMouseDown={close}>
      <CommandPalette onClose={close} className="w-[640px] animate-pop" />
    </div>
  )
}

export interface CommandPaletteProps {
  onClose: () => void
  /**
   * Standalone: the palette lives in its own window (panels mode) with its own gateway connection, so
   * anything that must land in the Hermes window is relayed there instead of run locally.
   */
  standalone?: boolean
  /** Standalone hosts show the launcher themselves; the desktop toggles the overlay store. */
  onApplications?: () => void
  className?: string
}

/** The palette itself, without backdrop: shared by the in-window command bar and the panels-mode overlay. */
export function CommandPalette({ onClose, standalone = false, onApplications, className }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const sessions = useStore($sessions)
  const slash = useSlashCatalog()
  const { apps } = useNativeApps()

  const close = onClose
  const ask = async (text: string) => {
    close()

    if (standalone) {
      relayToMain({ type: 'send-prompt', text })
      openSurface('main')

      return
    }

    showPage('hermes')

    if (text.startsWith('/')) {
      await runSlash(text)
    } else {
      await sendPrompt(text)
    }
  }

  const openSession = (id: string) => {
    close()

    if (standalone) {
      relayToMain({ type: 'open-session', args: [id] })
      openSurface('main')

      return
    }

    showPage('hermes')
    void openStoredSession(id)
  }

  const applications = () => {
    if (onApplications) {
      onApplications()

      return
    }

    $applicationsOpen.set(true)
    close()
  }

  const trimmed = query.trim()
  const isSlash = trimmed.startsWith('/')
  const needle = trimmed.toLowerCase()
  const matches = (label: string) => !needle || label.toLowerCase().includes(needle)
  const filteredApps = useMemo(() => (isSlash ? [] : HERMES_APPS.filter(app => app.id !== 'chat-popout' && matches(app.name))), [isSlash, needle])
  const filteredSessions = useMemo(() => (isSlash ? [] : sessions.filter(session => matches(session.title ?? session.preview ?? '')).slice(0, 8)), [isSlash, needle, sessions])
  const filteredSlash = useMemo(() => {
    if (!isSlash) {
      return []
    }

    const word = trimmed.slice(1).toLowerCase().split(/\s+/)[0] ?? ''

    return slash.filter(entry => entry.name.toLowerCase().startsWith(word)).slice(0, 12)
  }, [isSlash, slash, trimmed])
  const filteredNative = useMemo(() => {
    if (trimmed.length < 2 || isSlash) {
      return []
    }

    return apps.filter(app => app.name.toLowerCase().includes(needle)).slice(0, 6)
  }, [apps, isSlash, needle, trimmed.length])

  return (
    <Command
      label="Hermes command bar"
      shouldFilter={false}
      className={cn('float overflow-hidden rounded-2xl', className)}
      onMouseDown={event => event.stopPropagation()}
      onKeyDown={event => {
        if (event.key === 'Escape') {
          close()
        }
      }}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <HermesAvatar size={22} rounded={6} />
        <Command.Input autoFocus value={query} onValueChange={setQuery} placeholder="Ask Hermes anything, or type / for commands" className="h-7 flex-1 bg-transparent text-[15px] text-fg placeholder:text-fg-4 outline-none" />
        <Kbd>esc</Kbd>
      </div>
      <div className="h-px bg-line" />
      <Command.List className="max-h-[420px] overflow-y-auto p-2 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-fg-3 [&_[cmdk-group-heading]]:uppercase">
        {trimmed && (
          <Command.Group heading="Hermes">
            <Item value={`ask:${trimmed}`} onSelect={() => void ask(trimmed)} icon={<IconMessage size={15} />} hint="↵">
              {isSlash ? `Run ${trimmed}` : `Ask Hermes: “${trimmed}”`}
            </Item>
          </Command.Group>
        )}

        {isSlash && filteredSlash.length > 0 && (
          <Command.Group heading="Commands">
            {filteredSlash.map(entry => (
              <Item key={entry.name} value={`slash:${entry.name}`} onSelect={() => void ask(`/${entry.name}`)} icon={<IconSlash size={15} />} hint={entry.description}>
                /{entry.name}
              </Item>
            ))}
          </Command.Group>
        )}

        {filteredNative.length > 0 && (
          <Command.Group heading="Open app">
            {filteredNative.map(app => (
              <Item
                key={app.path}
                value={`app:${app.name}`}
                onSelect={() => {
                  window.hermesOS.apps.launch(app.path).catch(() => undefined)
                  close()
                }}
                icon={<IconArrowRight size={15} />}
                hint="Launch"
              >
                {app.name}
              </Item>
            ))}
          </Command.Group>
        )}

        {filteredApps.length > 0 && (
          <Command.Group heading="Go to">
            {filteredApps.map(app => (
              <Item
                key={app.id}
                value={`page:${app.name}`}
                onSelect={() => {
                  openApp(app.id)
                  close()
                }}
                icon={<AppGlyph id={app.icon} size={15} />}
                hint={app.shortcut ? `⌘${app.shortcut}` : undefined}
              >
                {app.name}
              </Item>
            ))}
            <Item value="page:applications" onSelect={applications} icon={<AppGlyph id="grid" size={15} />} hint="⌘⇧A">
              Applications
            </Item>
          </Command.Group>
        )}

        {filteredSessions.length > 0 && (
          <Command.Group heading="Recent sessions">
            {filteredSessions.map(session => (
              <Item key={session.id} value={`session:${session.title ?? session.preview ?? session.id}`} onSelect={() => openSession(session.id)} icon={<IconMessage size={15} />}>
                {session.title || session.preview || 'Untitled session'}
              </Item>
            ))}
          </Command.Group>
        )}
      </Command.List>
    </Command>
  )
}

function Item({ value, onSelect, icon, hint, children }: { value: string; onSelect: () => void; icon: React.ReactNode; hint?: string; children: React.ReactNode }) {
  return (
    <Command.Item value={value} onSelect={onSelect} className="flex h-9 cursor-pointer items-center gap-3 rounded-lg px-2.5 text-[13px] text-fg-2 data-[selected=true]:bg-white/10 data-[selected=true]:text-fg">
      <span className="flex size-5 items-center justify-center text-fg-3">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {hint && <span className="max-w-[45%] truncate text-[11px] text-fg-4">{hint}</span>}
    </Command.Item>
  )
}
