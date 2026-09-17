import { IconCheck } from '@tabler/icons-react'
import type React from 'react'
import { useEffect, useRef } from 'react'
import { cn } from '../../lib/cn.ts'

/*
 * A small anchored glass menu for the Files page. Render it inside a `relative` wrapper next to
 * the button that opened it; it closes on outside click and Escape.
 */

export interface MenuItemDef {
  id: string
  label: string
  icon?: React.ReactNode
  onSelect: () => void
  danger?: boolean
  checked?: boolean
  disabled?: boolean
  /** Draw a divider above this item. */
  dividerBefore?: boolean
}

export function Menu({ items, onClose, align = 'right', className }: { items: MenuItemDef[]; onClose: () => void; align?: 'left' | 'right'; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) {
        onClose()
      }
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey, true)

    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [onClose])

  return (
    <div
      ref={ref}
      role="menu"
      className={cn('float absolute z-30 min-w-48 rounded-xl p-1 animate-pop', align === 'right' ? 'right-0' : 'left-0', className)}
      onClick={event => event.stopPropagation()}
      onDoubleClick={event => event.stopPropagation()}
      onMouseDown={event => event.stopPropagation()}
    >
      {items.map(item => (
        <div key={item.id} className={cn(item.dividerBefore && 'mt-1 border-t border-line pt-1')}>
          <button
            type="button"
            role="menuitem"
            disabled={item.disabled}
            onClick={() => {
              onClose()
              item.onSelect()
            }}
            className={cn(
              'flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[12.5px] whitespace-nowrap hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-40 [&_svg]:size-[15px] [&_svg]:shrink-0',
              item.danger ? 'text-danger hover:bg-danger/12' : 'text-fg-2 hover:text-fg'
            )}
          >
            {item.icon && <span className={cn(item.danger ? 'text-danger' : 'text-fg-3')}>{item.icon}</span>}
            <span className="flex-1">{item.label}</span>
            {item.checked && <IconCheck size={14} className="text-accent-strong" />}
          </button>
        </div>
      ))}
    </div>
  )
}
