import { IconAppWindow, IconApps, IconCamera, IconClipboard, IconFolder, IconLock, IconLogout, IconMoon, IconPaperclip, IconPower, IconRefresh, IconSettings, IconTerminal2 } from '@tabler/icons-react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ShellCommand, WmWindow } from '../../../shared/ipc.ts'
import { HermesAvatar } from '../../components/app-icon.tsx'
import { EmptyGlass, GlassButton, Pill } from '../../components/ui/glass.tsx'
import { Kbd } from '../../components/ui/primitives.tsx'
import { cn } from '../../lib/cn.ts'
import { closeThisSurface, openSurface, relayToMain, wmAction } from '../../store/shell.ts'
import { openApp, showPage } from '../../store/windows.ts'
import { ApplicationsPanel } from '../apps/ApplicationsOverlay.tsx'
import { CommandPalette } from '../shell/CommandBar.tsx'
import { useShellCommands, windowLabel } from './shell-utils.ts'

type Mode = 'ask' | 'command' | 'applications' | 'menu' | 'power' | 'clipboard'

const MODES = new Set<Mode>(['ask', 'command', 'applications', 'menu', 'power', 'clipboard'])
const WINDOW_WIDTH = 680
const MAX_HEIGHT = 560

interface AskState {
  text: string
  context: WmWindow | null
  attachments: string[]
}

/**
 * Panels mode: one transparent overlay window (680 wide) niri centres over everything. The inbound
 * command picks what it shows: ask (about the focused window), the command palette, the launcher,
 * the Hermes OS menu, power actions or clipboard history. Escape (or losing focus) closes it.
 */
export function CommandSurface() {
  const [mode, setMode] = useState<Mode | null>(null)
  const [ask, setAsk] = useState<AskState>({ text: '', context: null, attachments: [] })
  const panelRef = useRef<HTMLDivElement>(null)

  useShellCommands((command: ShellCommand) => {
    if (command.type === 'payload') {
      return
    }

    if (command.type === 'ask' || (!MODES.has(command.type as Mode) && (command.text || command.context))) {
      setAsk({ text: command.text ?? '', context: command.context ?? null, attachments: command.attachments ?? [] })
      setMode('ask')

      return
    }

    if (MODES.has(command.type as Mode)) {
      setMode(command.type as Mode)
    }
  })

  // Opened without a command (or the command was lost): behave like the command bar.
  useEffect(() => {
    const timer = window.setTimeout(() => setMode(current => current ?? 'command'), 250)

    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeThisSurface()
      }
    }
    window.addEventListener('keydown', onKey)

    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Hug the content: the transparent window shrinks to the panel so clicks outside reach other windows.
  useLayoutEffect(() => {
    const node = panelRef.current

    if (!node || typeof ResizeObserver === 'undefined') {
      return
    }

    let lastHeight = 0
    const fit = () => {
      const height = Math.min(MAX_HEIGHT, Math.ceil(node.getBoundingClientRect().height) + 4)

      if (height > 0 && height !== lastHeight) {
        lastHeight = height
        window.hermesOS.shell.resize(WINDOW_WIDTH, height).catch(() => undefined)
      }
    }
    const observer = new ResizeObserver(fit)
    observer.observe(node)
    fit()

    return () => observer.disconnect()
  }, [mode])

  const close = closeThisSurface

  if (!mode) {
    return null
  }

  return (
    <div className="flex h-full w-full items-start justify-center overflow-hidden text-fg">
      <div ref={panelRef} className="w-full">
        {mode === 'ask' && <AskPanel state={ask} onClose={close} />}
        {mode === 'command' && <CommandPalette standalone onClose={close} onApplications={() => setMode('applications')} className="w-full animate-pop" />}
        {mode === 'applications' && <ApplicationsPanel standalone onClose={close} className="h-[556px] w-full animate-pop" />}
        {mode === 'menu' && <MenuPanel onClose={close} onApplications={() => setMode('applications')} onPower={() => setMode('power')} />}
        {mode === 'power' && <PowerPanel onClose={close} />}
        {mode === 'clipboard' && <ClipboardPanel />}
      </div>
    </div>
  )
}

/** "Ask Hermes about this window": a prompt with the focused window as context, relayed to the Hermes window. */
function AskPanel({ state, onClose }: { state: AskState; onClose: () => void }) {
  const [text, setText] = useState(state.text)
  const textarea = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setText(state.text)
  }, [state.text])

  useEffect(() => {
    const node = textarea.current

    if (node) {
      node.focus()
      node.setSelectionRange(node.value.length, node.value.length)
    }
  }, [])

  const canSend = text.trim().length > 0 || state.attachments.length > 0

  const submit = () => {
    if (!canSend) {
      return
    }

    relayToMain({ type: 'send-prompt', text: text.trim(), context: state.context, attachments: state.attachments })
    openSurface('main')
    onClose()
  }

  return (
    <div className="float flex flex-col overflow-hidden rounded-2xl animate-pop">
      <div className="flex items-center gap-3 px-4 pt-4 pb-2">
        <HermesAvatar size={22} rounded={6} />
        <span className="text-[14px] font-semibold">Ask Hermes</span>
        <span className="flex-1" />
        <Kbd>esc</Kbd>
      </div>

      {(state.context || state.attachments.length > 0) && (
        <div className="flex flex-wrap items-center gap-1.5 px-4 pb-2">
          {state.context && (
            <Pill tone="accent" className="max-w-full">
              <IconAppWindow size={13} />
              <span className="truncate">{windowLabel(state.context)}</span>
              <span className="truncate text-fg-3">{state.context.appId}</span>
            </Pill>
          )}
          {state.attachments.map(path => (
            <Pill key={path} tone="muted" className="max-w-full">
              <IconPaperclip size={13} />
              <span className="truncate">{path.split('/').pop() || path}</span>
            </Pill>
          ))}
        </div>
      )}

      <div className="px-4 pb-3">
        <textarea
          ref={textarea}
          value={text}
          rows={3}
          onChange={event => setText(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
          placeholder={state.context ? `Ask about ${windowLabel(state.context)}` : 'Ask Hermes anything'}
          aria-label="Ask Hermes"
          className="glass-input w-full resize-none rounded-lg px-3 py-2.5 text-[14px] leading-relaxed outline-none placeholder:text-fg-4"
        />
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-3">
        <span className="text-[11.5px] text-fg-4">
          <Kbd>↵</Kbd> send · <Kbd>⇧↵</Kbd> new line
        </span>
        <GlassButton variant="primary" size="sm" onClick={submit} disabled={!canSend}>
          Send to Hermes
        </GlassButton>
      </div>
    </div>
  )
}

interface MenuAction {
  id: string
  label: string
  hint?: string
  icon: ReactNode
  disabled?: boolean
  run: () => void
}

/** The Hermes OS control menu: the same actions the `hermes-os` CLI exposes. */
function MenuPanel({ onClose, onApplications, onPower }: { onClose: () => void; onApplications: () => void; onPower: () => void }) {
  const [active, setActive] = useState(0)
  const actions: MenuAction[] = [
    { id: 'applications', label: 'Applications', hint: 'Launcher', icon: <IconApps size={16} />, run: onApplications },
    {
      id: 'terminal',
      label: 'Terminal',
      hint: 'Open a shell',
      icon: <IconTerminal2 size={16} />,
      run: () => {
        openApp('terminal')
        onClose()
      }
    },
    {
      id: 'files',
      label: 'Files',
      hint: 'Hermes window',
      icon: <IconFolder size={16} />,
      run: () => {
        showPage('files')
        onClose()
      }
    },
    {
      id: 'settings',
      label: 'Settings',
      hint: 'Hermes window',
      icon: <IconSettings size={16} />,
      run: () => {
        showPage('settings')
        onClose()
      }
    },
    {
      id: 'screenshot',
      label: 'Screenshot',
      hint: 'Whole screen',
      icon: <IconCamera size={16} />,
      run: () => {
        void wmAction({ type: 'screenshot', what: 'screen' })
        onClose()
      }
    },
    { id: 'lock', label: 'Lock', hint: 'Arrives in Phase 2', icon: <IconLock size={16} />, disabled: true, run: () => undefined },
    { id: 'power', label: 'Power', hint: 'Sleep, restart, shut down', icon: <IconPower size={16} />, run: onPower }
  ]

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault()
        setActive(current => (current + (event.key === 'ArrowDown' ? 1 : actions.length - 1)) % actions.length)
      } else if (event.key === 'Enter') {
        event.preventDefault()
        const action = actions[active]

        if (action && !action.disabled) {
          action.run()
        }
      }
    }
    window.addEventListener('keydown', onKey)

    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  return (
    <div className="float flex flex-col overflow-hidden rounded-2xl animate-pop">
      <div className="flex items-center gap-3 px-4 pt-4 pb-3">
        <HermesAvatar size={22} rounded={6} />
        <span className="text-[14px] font-semibold">Hermes OS</span>
        <span className="flex-1" />
        <Kbd>esc</Kbd>
      </div>
      <div className="h-px bg-line" />
      <div className="flex flex-col gap-0.5 p-2" role="menu">
        {actions.map((action, index) => (
          <button
            key={action.id}
            type="button"
            role="menuitem"
            disabled={action.disabled}
            onMouseEnter={() => setActive(index)}
            onClick={action.run}
            className={cn('flex h-10 items-center gap-3 rounded-lg px-3 text-[13px] text-fg-2 disabled:cursor-not-allowed disabled:opacity-50', index === active && !action.disabled && 'bg-white/10 text-fg')}
          >
            <span className="flex size-6 items-center justify-center text-fg-3">{action.icon}</span>
            <span className="flex-1 text-left">{action.label}</span>
            {action.hint && <span className="text-[11px] text-fg-4">{action.hint}</span>}
          </button>
        ))}
      </div>
    </div>
  )
}

const POWER_ACTIONS: { id: 'suspend' | 'reboot' | 'poweroff' | 'logout'; label: string; icon: ReactNode; danger?: boolean }[] = [
  { id: 'suspend', label: 'Sleep', icon: <IconMoon size={22} /> },
  { id: 'reboot', label: 'Restart', icon: <IconRefresh size={22} /> },
  { id: 'poweroff', label: 'Shut down', icon: <IconPower size={22} />, danger: true },
  { id: 'logout', label: 'Log out', icon: <IconLogout size={22} /> }
]

/** Power actions are relayed to the Hermes window, which owns the (Phase 2) machine-side handler. */
function PowerPanel({ onClose }: { onClose: () => void }) {
  return (
    <div className="float flex flex-col overflow-hidden rounded-2xl animate-pop">
      <div className="flex items-center gap-3 px-4 pt-4 pb-3">
        <HermesAvatar size={22} rounded={6} />
        <span className="text-[14px] font-semibold">Power</span>
        <span className="flex-1" />
        <Kbd>esc</Kbd>
      </div>
      <div className="h-px bg-line" />
      <div className="grid grid-cols-4 gap-3 p-4">
        {POWER_ACTIONS.map((action, index) => (
          <button
            key={action.id}
            type="button"
            autoFocus={index === 0}
            onClick={() => {
              relayToMain({ type: 'power', args: [action.id] })
              onClose()
            }}
            className={cn('glass-card glass-card-hover flex flex-col items-center gap-2.5 rounded-xl px-3 py-4 text-[12.5px] text-fg-2 hover:text-fg', action.danger && 'hover:border-danger/50 hover:text-danger')}
          >
            <span className={cn('icon-tile size-11 rounded-xl', action.danger && 'text-danger')}>{action.icon}</span>
            {action.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function ClipboardPanel() {
  return (
    <div className="float flex flex-col overflow-hidden rounded-2xl animate-pop">
      <div className="flex items-center gap-3 px-4 pt-4 pb-3">
        <HermesAvatar size={22} rounded={6} />
        <span className="text-[14px] font-semibold">Clipboard</span>
        <span className="flex-1" />
        <Kbd>esc</Kbd>
      </div>
      <div className="h-px bg-line" />
      <div className="p-4">
        <EmptyGlass icon={<IconClipboard />} title="Clipboard history arrives in Phase 2" description="Recent copies will be listed here, searchable and pasteable into any window." />
      </div>
    </div>
  )
}
