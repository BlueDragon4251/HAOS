import { useStore } from '@nanostores/react'
import { IconArrowRight, IconMessage, IconSlash } from '@tabler/icons-react'
import { Command } from 'cmdk'
import { useEffect, useMemo, useState } from 'react'
import type { InstalledApp } from '../../../shared/ipc.ts'
import { BrandMark } from '../../components/brand-mark.tsx'
import { Kbd } from '../../components/ui/primitives.tsx'
import { $sessions } from '../../store/sessions.ts'
import { openStoredSession, runSlash, sendPrompt } from '../../store/chat.ts'
import { $commandBarOpen, showSurface, toggleCommandBar } from '../../store/surface.ts'
import { SURFACES } from '../surfaces.ts'
import { useSlashCatalog } from '../chat/use-slash-catalog.ts'

/**
 * The global command bar: type to talk to Hermes, or jump to a surface, session, app or slash
 * command. Enter on free text sends it to Hermes and opens the chat.
 */
export function CommandBar() {
  const [query, setQuery] = useState('')
  const sessions = useStore($sessions)
  const open = useStore($commandBarOpen)
  const slash = useSlashCatalog()
  const [apps, setApps] = useState<InstalledApp[]>([])

  useEffect(() => {
    void window.hermesOS.apps.list().then(setApps).catch(() => setApps([]))
  }, [])

  const close = () => toggleCommandBar(false)
  const ask = async (text: string) => {
    close()
    showSurface('chat')

    if (text.startsWith('/')) {
      await runSlash(text)
    } else {
      await sendPrompt(text)
    }
  }

  const trimmed = query.trim()
  const isSlash = trimmed.startsWith('/')
  const needle = trimmed.toLowerCase()
  const matches = (label: string) => !needle || label.toLowerCase().includes(needle)
  const filteredSurfaces = useMemo(() => (isSlash ? [] : SURFACES.filter(surface => matches(surface.label))), [isSlash, needle])
  const filteredSessions = useMemo(
    () => (isSlash ? [] : sessions.filter(session => matches(session.title ?? session.preview ?? '')).slice(0, 8)),
    [isSlash, needle, sessions]
  )
  const filteredSlash = useMemo(() => {
    if (!isSlash) {
      return []
    }

    const needle = trimmed.slice(1).toLowerCase().split(/\s+/)[0] ?? ''

    return slash.filter(entry => entry.name.toLowerCase().startsWith(needle)).slice(0, 12)
  }, [isSlash, slash, trimmed])
  const filteredApps = useMemo(() => {
    if (trimmed.length < 2 || isSlash) {
      return []
    }

    const needle = trimmed.toLowerCase()

    return apps.filter(app => app.name.toLowerCase().includes(needle)).slice(0, 6)
  }, [apps, isSlash, trimmed])

  if (!open) {
    return null
  }

  return (
    <div className="absolute inset-0 z-(--z-command) flex items-start justify-center bg-black/40 pt-[14vh] animate-fade-in" onMouseDown={close}>
      <Command
        label="Hermes command bar"
        shouldFilter={false}
        className="float w-[640px] overflow-hidden rounded-xl animate-rise"
        onMouseDown={event => event.stopPropagation()}
        onKeyDown={event => {
          if (event.key === 'Escape') {
            close()
          }
        }}
      >
        <div className="flex items-center gap-3 px-4 py-3">
          <BrandMark size={18} />
          <Command.Input
            autoFocus
            value={query}
            onValueChange={setQuery}
            placeholder="Ask Hermes anything, or type / for commands"
            className="h-7 flex-1 bg-transparent text-[15px] text-fg placeholder:text-fg-4 outline-none"
          />
          <Kbd>esc</Kbd>
        </div>
        <div className="h-px bg-hairline" />
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

          {filteredApps.length > 0 && (
            <Command.Group heading="Open app">
              {filteredApps.map(app => (
                <Item key={app.path} value={`app:${app.name}`} onSelect={() => { void window.hermesOS.apps.launch(app.path); close() }} icon={<IconArrowRight size={15} />} hint="Launch">
                  {app.name}
                </Item>
              ))}
            </Command.Group>
          )}

          {filteredSurfaces.length > 0 && (
            <Command.Group heading="Go to">
              {filteredSurfaces.map(surface => {
                const Icon = surface.icon

                return (
                  <Item key={surface.id} value={`surface:${surface.label}`} onSelect={() => { showSurface(surface.id); close() }} icon={<Icon size={15} />} hint={`⌘${surface.shortcut}`}>
                    {surface.label}
                  </Item>
                )
              })}
            </Command.Group>
          )}

          {filteredSessions.length > 0 && (
            <Command.Group heading="Recent sessions">
              {filteredSessions.map(session => (
                <Item
                  key={session.id}
                  value={`session:${session.title ?? session.preview ?? session.id}`}
                  onSelect={() => { close(); showSurface('chat'); void openStoredSession(session.id) }}
                  icon={<IconMessage size={15} />}
                >
                  {session.title || session.preview || 'Untitled session'}
                </Item>
              ))}
            </Command.Group>
          )}
        </Command.List>
      </Command>
    </div>
  )
}

function Item({ value, onSelect, icon, hint, children }: { value: string; onSelect: () => void; icon: React.ReactNode; hint?: string; children: React.ReactNode }) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex h-9 cursor-pointer items-center gap-3 rounded-md px-2.5 text-[13px] text-fg-2 data-[selected=true]:bg-white/6 data-[selected=true]:text-fg"
    >
      <span className="flex size-5 items-center justify-center text-fg-3">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {hint && <span className="max-w-[45%] truncate text-[11px] text-fg-4">{hint}</span>}
    </Command.Item>
  )
}
