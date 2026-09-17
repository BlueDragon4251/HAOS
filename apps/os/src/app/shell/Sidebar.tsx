import { useStore } from '@nanostores/react'
import { IconPlus } from '@tabler/icons-react'
import { useState } from 'react'
import { AppGlyph, HermesAvatar } from '../../components/app-icon.tsx'
import { cn } from '../../lib/cn.ts'
import { $activeSpace, $spaces, addSpace, setActiveSpace } from '../../store/spaces.ts'
import { $page, showPage } from '../../store/windows.ts'
import { PAGES } from '../apps.ts'

/** The persistent left rail of the main Hermes window: identity, pages, spaces. */
export function Sidebar() {
  const page = useStore($page)
  const spaces = useStore($spaces)
  const active = useStore($activeSpace)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')

  return (
    <aside className="flex w-[132px] shrink-0 flex-col px-3 pt-4 pb-4 select-none">
      <div className="px-1">
        <HermesAvatar size={44} rounded={11} />
        <div className="mt-2.5 text-[15px] font-semibold leading-tight text-fg">Hermes</div>
        <div className="mt-0.5 text-[11px] leading-snug text-fg-3 italic">A more capable you. Always.</div>
      </div>

      <nav className="relative mt-5 flex flex-col gap-0.5" aria-label="Pages">
        {PAGES.map(def => {
          const activePage = def.id === page

          return (
            <button
              key={def.id}
              type="button"
              onClick={() => showPage(def.id)}
              aria-current={activePage ? 'page' : undefined}
              className={cn(
                'relative flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[12.5px] transition-colors duration-150',
                activePage ? 'bg-accent text-accent-fg shadow-[0_4px_16px_rgba(47,125,255,.45)]' : 'text-fg-2 hover:bg-white/8 hover:text-fg'
              )}
            >
              <AppGlyph id={def.icon} size={16} stroke={1.9} className={activePage ? 'text-accent-fg' : 'text-fg-2'} />
              <span className="truncate">{def.name}</span>
            </button>
          )
        })}
      </nav>

      <div className="mx-1 my-4 h-px bg-line" />

      <div className="flex items-center justify-between px-2">
        <span className="text-[10px] font-semibold tracking-[0.14em] text-fg-3 uppercase">Spaces</span>
        <button type="button" aria-label="Add space" onClick={() => setAdding(true)} className="flex size-5 items-center justify-center rounded text-fg-3 hover:bg-white/10 hover:text-fg">
          <IconPlus size={13} />
        </button>
      </div>
      <div className="mt-1.5 flex flex-col gap-0.5">
        {spaces.map(space => {
          const on = space.id === active.id

          return (
            <button
              key={space.id}
              type="button"
              onClick={() => setActiveSpace(space.id)}
              className={cn('flex h-7 items-center gap-2.5 rounded-lg px-2.5 text-[12.5px] transition-colors duration-150', on ? 'bg-white/14 text-fg' : 'text-fg-2 hover:bg-white/8 hover:text-fg')}
            >
              <span className="size-2 rounded-full shadow-[0_0_8px_currentColor]" style={{ background: space.color, color: space.color }} />
              <span className="truncate">{space.name}</span>
            </button>
          )
        })}
        {adding && (
          <input
            autoFocus
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onBlur={() => {
              setAdding(false)
              setDraft('')
            }}
            onKeyDown={e => {
              if (e.key === 'Enter' && draft.trim()) {
                addSpace(draft.trim())
                setAdding(false)
                setDraft('')
              }

              if (e.key === 'Escape') {
                setAdding(false)
                setDraft('')
              }
            }}
            placeholder="New space"
            className="glass-input mt-1 h-7 rounded-lg px-2.5 text-[12.5px] outline-none"
          />
        )}
      </div>
    </aside>
  )
}
