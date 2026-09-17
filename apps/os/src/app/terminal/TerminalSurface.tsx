import { IconPlus, IconX } from '@tabler/icons-react'
import { FitAddon } from '@xterm/addon-fit'
import { WebglAddon } from '@xterm/addon-webgl'
import { Terminal } from '@xterm/xterm'
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/button.tsx'
import { EmptyState } from '../../components/ui/primitives.tsx'
import { cn } from '../../lib/cn.ts'

interface Tab {
  id: string
  title: string
}

const THEME = {
  background: '#0c0e12',
  foreground: '#e6e8eb',
  cursor: '#e6b84a',
  cursorAccent: '#0c0e12',
  selectionBackground: 'rgba(230, 184, 74, 0.25)',
  black: '#1a1d24',
  red: '#e5645b',
  green: '#5fc98a',
  yellow: '#e3a54a',
  blue: '#6aa9ff',
  magenta: '#c58af9',
  cyan: '#5fd1d6',
  white: '#c9ced6',
  brightBlack: '#5b6270',
  brightRed: '#f08078',
  brightGreen: '#7fe0a6',
  brightYellow: '#f0c070',
  brightBlue: '#8fbfff',
  brightMagenta: '#d7a8ff',
  brightCyan: '#84e6ea',
  brightWhite: '#f4f6f8'
}

/** Real shells in real PTYs. Tabs stay alive when the surface is hidden. */
export function TerminalSurface() {
  const [tabs, setTabs] = useState<Tab[]>([])
  const [active, setActive] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pending = useRef(false)

  const create = async () => {
    if (pending.current) {
      return
    }

    pending.current = true

    try {
      const handle = await window.hermesOS.terminal.create({ cols: 120, rows: 30 })
      setTabs(current => [...current, { id: handle.id, title: handle.shell.split('/').pop() ?? 'shell' }])
      setActive(handle.id)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      pending.current = false
    }
  }

  useEffect(() => {
    if (tabs.length === 0 && !error) {
      void create()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(
    () =>
      window.hermesOS.terminal.onExit(id => {
        setTabs(current => {
          const next = current.filter(tab => tab.id !== id)
          setActive(prev => (prev === id ? (next[next.length - 1]?.id ?? null) : prev))

          return next
        })
      }),
    []
  )

  const close = (id: string) => {
    void window.hermesOS.terminal.dispose(id)
    setTabs(current => {
      const next = current.filter(tab => tab.id !== id)
      setActive(prev => (prev === id ? (next[next.length - 1]?.id ?? null) : prev))

      return next
    })
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 px-3">
        {tabs.map(tab => (
          <div key={tab.id} className={cn('group flex h-7 items-center gap-1 rounded-sm pr-1 pl-2.5 text-[12px]', tab.id === active ? 'bg-white/8 text-fg' : 'text-fg-3 hover:bg-white/4 hover:text-fg-2')}>
            <button type="button" onClick={() => setActive(tab.id)} className="font-mono">
              {tab.title}
            </button>
            <button type="button" aria-label="Close terminal" onClick={() => close(tab.id)} className="flex size-5 items-center justify-center rounded-xs text-fg-4 opacity-0 group-hover:opacity-100 hover:text-fg">
              <IconX size={12} />
            </button>
          </div>
        ))}
        <Button variant="ghost" size="icon-sm" aria-label="New terminal" onClick={() => void create()}>
          <IconPlus size={15} />
        </Button>
      </div>
      <div className="relative min-h-0 flex-1 px-3 pb-3">
        {error && (
          <EmptyState title="Terminal unavailable" description={error} action={<Button onClick={() => { setError(null); void create() }}>Try again</Button>} />
        )}
        {tabs.map(tab => (
          <TerminalView key={tab.id} id={tab.id} active={tab.id === active} />
        ))}
      </div>
    </div>
  )
}

function TerminalView({ id, active }: { id: string; active: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  const term = useRef<Terminal | null>(null)
  const fit = useRef<FitAddon | null>(null)

  useEffect(() => {
    const el = host.current

    if (!el) {
      return
    }

    const terminal = new Terminal({
      theme: THEME,
      fontFamily: 'SF Mono, JetBrains Mono, Menlo, monospace',
      fontSize: 12.5,
      lineHeight: 1.25,
      cursorBlink: true,
      cursorStyle: 'bar',
      allowProposedApi: true,
      scrollback: 8000,
      macOptionIsMeta: true
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    terminal.open(el)

    try {
      terminal.loadAddon(new WebglAddon())
    } catch {
      // Canvas renderer fallback is automatic.
    }

    term.current = terminal
    fit.current = fitAddon
    const offData = window.hermesOS.terminal.onData((tid, data) => {
      if (tid === id) {
        terminal.write(data)
      }
    })
    const onInput = terminal.onData(data => window.hermesOS.terminal.write(id, data))
    const onResize = terminal.onResize(({ cols, rows }) => window.hermesOS.terminal.resize(id, cols, rows))
    const observer = new ResizeObserver(() => {
      if (el.clientWidth > 0 && el.clientHeight > 0) {
        fitAddon.fit()
      }
    })
    observer.observe(el)
    fitAddon.fit()

    return () => {
      observer.disconnect()
      offData()
      onInput.dispose()
      onResize.dispose()
      terminal.dispose()
      term.current = null
    }
  }, [id])

  useEffect(() => {
    if (active) {
      requestAnimationFrame(() => {
        fit.current?.fit()
        term.current?.focus()
      })
    }
  }, [active])

  return <div ref={host} className={cn('absolute inset-x-3 inset-y-0 bottom-3 overflow-hidden rounded-lg bg-bg-elevated hairline', !active && 'invisible')} />
}
