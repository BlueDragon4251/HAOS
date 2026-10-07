import {
  IconAdjustments,
  IconChevronDown,
  IconChevronRight,
  IconCopy,
  IconCornerLeftDown,
  IconEye,
  IconEyeOff,
  IconFolder,
  IconFolderOpen,
  IconFolderPlus,
  IconLetterT,
  IconMask,
  IconPlus,
  IconTrash
} from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { BLEND_MODES, type BlendMode } from '../../../shared/canvas/comp-format.ts'
import { cn } from '../../lib/cn.ts'
import { addFolder, addLayer, addMask, deletePicked, duplicatePicked, rename, setBlendMode, toggleClipping, toggleVisible } from './actions.ts'
import { type CanvasDocument, type CanvasLayer, childrenOf, type DocState, moveLayer, withLayer } from './engine/document.ts'
import type { Raster } from './engine/raster.ts'
import { useRevision } from './hooks.ts'

const DRAG_TYPE = 'application/x-herald-canvas-layer'

/** Blend modes in their usual families, each family after a divider. */
const FAMILIES: BlendMode[][] = [BLEND_MODES.slice(0, 1), BLEND_MODES.slice(1, 5), BLEND_MODES.slice(5, 9), BLEND_MODES.slice(9, 16), BLEND_MODES.slice(16, 20), BLEND_MODES.slice(20)]

const CHECKER = 'repeating-conic-gradient(rgba(255,255,255,0.22) 0% 25%, rgba(255,255,255,0.08) 0% 50%) 50% / 8px 8px'

interface Row {
  layer: CanvasLayer
  depth: number
}

/** The tree top first, as the panel lists it, without the insides of collapsed folders. */
function rowsOf(state: DocState, collapsed: ReadonlySet<string>, parentID?: string, depth = 0, out: Row[] = []): Row[] {
  const children = childrenOf(state, parentID)

  for (let i = children.length - 1; i >= 0; i--) {
    const layer = children[i]
    out.push({ layer, depth })

    if (layer.isGroup && !collapsed.has(layer.id)) {
      rowsOf(state, collapsed, layer.id, depth + 1, out)
    }
  }

  return out
}

/** A small preview of a raster, fitted and sampled (cheap enough to redraw on every stroke). */
function Thumb({ raster, version, size = 32 }: { raster: Raster | null; version: number; size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    const context = canvas?.getContext('2d')

    if (!canvas || !context) {
      return
    }

    context.clearRect(0, 0, canvas.width, canvas.height)

    if (!raster) {
      return
    }

    const side = canvas.width
    const ratio = Math.min(side / raster.width, side / raster.height)
    const width = Math.max(1, Math.round(raster.width * ratio))
    const height = Math.max(1, Math.round(raster.height * ratio))
    const image = context.createImageData(width, height)

    for (let y = 0; y < height; y++) {
      const sy = Math.min(raster.height - 1, Math.floor(((y + 0.5) * raster.height) / height))

      for (let x = 0; x < width; x++) {
        const sx = Math.min(raster.width - 1, Math.floor(((x + 0.5) * raster.width) / width))
        const o = (y * width + x) * 4

        if (raster.channels === 4) {
          const s = (sy * raster.width + sx) * 4
          image.data[o] = raster.data[s]
          image.data[o + 1] = raster.data[s + 1]
          image.data[o + 2] = raster.data[s + 2]
          image.data[o + 3] = raster.data[s + 3]
        } else {
          const v = raster.data[sy * raster.width + sx]
          image.data[o] = image.data[o + 1] = image.data[o + 2] = v
          image.data[o + 3] = 255
        }
      }
    }

    context.putImageData(image, Math.floor((side - width) / 2), Math.floor((side - height) / 2))
  }, [raster, version])

  return <canvas ref={ref} width={size * 2} height={size * 2} className="shrink-0 rounded-[4px] ring-1 ring-line" style={{ width: size, height: size, background: CHECKER }} />
}

function LayerRow({
  doc,
  row,
  picked,
  renaming,
  onRename,
  collapsed,
  onToggleCollapsed,
  drop,
  onDragOver,
  onDrop
}: {
  doc: CanvasDocument
  row: Row
  picked: boolean
  renaming: boolean
  onRename: (id: string | null) => void
  collapsed: boolean
  onToggleCollapsed: () => void
  drop: 'above' | 'below' | 'into' | null
  onDragOver: (event: React.DragEvent, layer: CanvasLayer) => void
  onDrop: (event: React.DragEvent) => void
}) {
  const { layer, depth } = row
  const [draft, setDraft] = useState(layer.name)
  const clipped = Boolean(layer.maskSourceID)

  useEffect(() => {
    if (renaming) {
      setDraft(layer.name)
    }
  }, [renaming, layer.name])

  const finish = (keep: boolean) => {
    if (keep) {
      rename(doc, layer, draft)
    }

    onRename(null)
  }

  return (
    <div
      role="treeitem"
      aria-selected={picked}
      aria-expanded={layer.isGroup ? !collapsed : undefined}
      draggable={!renaming}
      onDragStart={(event) => {
        event.dataTransfer.setData(DRAG_TYPE, layer.id)
        event.dataTransfer.effectAllowed = 'move'
      }}
      onDragOver={(event) => onDragOver(event, layer)}
      onDrop={onDrop}
      onClick={(event) => doc.select(layer.id, event.shiftKey || event.metaKey || event.ctrlKey)}
      onDoubleClick={() => onRename(layer.id)}
      className={cn(
        'group relative flex h-11 shrink-0 cursor-default items-center gap-1.5 border-b border-line/50 pr-2 text-[12px]',
        picked ? 'bg-accent/18 text-fg' : 'text-fg-2 hover:bg-white/5',
        drop === 'into' && 'bg-accent/25 ring-1 ring-inset ring-accent'
      )}
      style={{ paddingLeft: 4 + depth * 14 }}
    >
      {drop === 'above' && <div className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-accent" />}
      {drop === 'below' && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-0.5 bg-accent" />}
      <button
        type="button"
        aria-label={layer.isVisible ? 'Hide layer' : 'Show layer'}
        onClick={(event) => {
          event.stopPropagation()
          toggleVisible(doc, layer)
        }}
        className="grid size-6 shrink-0 place-items-center rounded text-fg-3 hover:text-fg"
      >
        {layer.isVisible ? <IconEye size={15} /> : <IconEyeOff size={15} className="opacity-60" />}
      </button>
      {layer.isGroup ? (
        <button
          type="button"
          aria-label={collapsed ? 'Expand folder' : 'Collapse folder'}
          onClick={(event) => {
            event.stopPropagation()
            onToggleCollapsed()
          }}
          className="grid size-4 shrink-0 place-items-center text-fg-3 hover:text-fg"
        >
          {collapsed ? <IconChevronRight size={13} /> : <IconChevronDown size={13} />}
        </button>
      ) : clipped ? (
        <IconCornerLeftDown size={13} className="shrink-0 text-fg-3" aria-label="Clipped to the layer below" />
      ) : (
        <span className="w-4 shrink-0" />
      )}
      {layer.isGroup ? (
        <span className="grid size-8 shrink-0 place-items-center text-fg-3">{collapsed ? <IconFolder size={20} /> : <IconFolderOpen size={20} />}</span>
      ) : layer.adjustment ? (
        <span className="grid size-8 shrink-0 place-items-center rounded-[4px] bg-white/6 text-fg-2 ring-1 ring-line">
          <IconAdjustments size={17} />
        </span>
      ) : (
        <Thumb raster={layer.pixels} version={layer.pixels?.version ?? 0} />
      )}
      {layer.mask && (
        <span className={cn(layer.maskEnabled === false && 'opacity-35')} title={layer.maskEnabled === false ? 'Mask turned off' : 'Mask'}>
          <Thumb raster={layer.mask} version={layer.mask.version} size={24} />
        </span>
      )}
      <div className="min-w-0 flex-1 pl-1">
        {renaming ? (
          <input
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => finish(true)}
            onKeyDown={(event) => {
              event.stopPropagation()

              if (event.key === 'Enter') {
                finish(true)
              } else if (event.key === 'Escape') {
                finish(false)
              }
            }}
            onClick={(event) => event.stopPropagation()}
            className="glass-input h-6 w-full rounded px-1.5 text-[12px] text-fg outline-none"
          />
        ) : (
          <div className={cn('flex items-center gap-1 truncate', !layer.isVisible && 'opacity-55')}>
            {layer.text && <IconLetterT size={12} className="shrink-0 text-fg-3" />}
            <span className="truncate">{layer.name}</span>
          </div>
        )}
        {!renaming && ((layer.opacity ?? 1) < 1 || (layer.blendMode && layer.blendMode !== 'Normal')) && (
          <div className="truncate text-[10.5px] text-fg-3">
            {[layer.blendMode !== 'Normal' ? layer.blendMode : null, (layer.opacity ?? 1) < 1 ? `${Math.round((layer.opacity ?? 1) * 100)}%` : null].filter(Boolean).join(' · ')}
          </div>
        )}
      </div>
    </div>
  )
}

/** The active layer's blend mode and opacity. */
function LayerControls({ doc, layer }: { doc: CanvasDocument; layer: CanvasLayer | undefined }) {
  const before = useRef<DocState | null>(null)
  const opacity = Math.round((layer?.opacity ?? 1) * 100)

  const setOpacity = (value: number) => {
    if (!layer) {
      return
    }

    const next = Math.max(0, Math.min(100, value)) / 100

    if (before.current) {
      doc.preview(withLayer(before.current, layer.id, { opacity: next }))
    } else {
      doc.commit('Opacity Change', withLayer(doc.state, layer.id, { opacity: next }))
    }
  }

  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-line px-2.5 py-2">
      <select
        aria-label="Blend mode"
        disabled={!layer || layer.isGroup}
        value={layer?.isGroup ? 'Pass Through' : (layer?.blendMode ?? 'Normal')}
        onChange={(event) => layer && setBlendMode(doc, layer, event.target.value as BlendMode)}
        className="glass-input h-7 min-w-0 flex-1 rounded-md px-1.5 text-[12px] text-fg outline-none disabled:opacity-50"
      >
        {layer?.isGroup && <option value="Pass Through">Pass Through</option>}
        {FAMILIES.map((family, i) => (
          <optgroup key={i} label={i === 0 ? 'Normal' : ' '}>
            {family.map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <input
        type="range"
        aria-label="Opacity"
        min={0}
        max={100}
        disabled={!layer}
        value={opacity}
        onPointerDown={() => {
          before.current = doc.state
        }}
        onPointerUp={() => {
          if (before.current) {
            doc.commitFrom('Opacity Change', before.current)
            before.current = null
          }
        }}
        onChange={(event) => setOpacity(Number(event.target.value))}
        className="w-20 accent-[var(--color-accent,#4da3ff)]"
      />
      <span className="w-9 text-right text-[11.5px] tabular-nums text-fg-2">{opacity}%</span>
    </div>
  )
}

export function LayersPanel({ doc }: { doc: CanvasDocument }) {
  useRevision(doc)
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())
  const [renaming, setRenaming] = useState<string | null>(null)
  const [drop, setDrop] = useState<{ id: string; where: 'above' | 'below' | 'into' } | null>(null)
  const { state } = doc
  const rows = rowsOf(state, collapsed)
  const picked = new Set(doc.picked.map((layer) => layer.id))
  const active = doc.active

  const onDragOver = (event: React.DragEvent, layer: CanvasLayer) => {
    if (!event.dataTransfer.types.includes(DRAG_TYPE)) {
      return
    }

    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    const rect = event.currentTarget.getBoundingClientRect()
    const at = (event.clientY - rect.top) / rect.height
    const where = layer.isGroup && at > 0.3 && at < 0.7 ? 'into' : at < 0.5 ? 'above' : 'below'

    if (drop?.id !== layer.id || drop.where !== where) {
      setDrop({ id: layer.id, where })
    }
  }

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault()
    const id = event.dataTransfer.getData(DRAG_TYPE)
    const target = drop && doc.layer(drop.id)
    setDrop(null)

    if (!id || !drop || !target || target.id === id) {
      return
    }

    if (drop.where === 'into') {
      const inside = childrenOf(state, target.id).filter((layer) => layer.id !== id)
      doc.commit('Move Layer', moveLayer(state, id, target.id, inside.length))

      return
    }

    const siblings = childrenOf(state, target.parentID).filter((layer) => layer.id !== id)
    const index = siblings.indexOf(target)
    // The panel lists top first: above a row is higher in the stack.
    doc.commit('Move Layer', moveLayer(state, id, target.parentID, drop.where === 'above' ? index + 1 : index))
  }

  const toggleCollapsed = (id: string) =>
    setCollapsed((current) => {
      const next = new Set(current)

      if (!next.delete(id)) {
        next.add(id)
      }

      return next
    })

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-8 shrink-0 items-center px-3 text-[11px] font-medium tracking-wide text-fg-3 uppercase">Layers</div>
      <LayerControls doc={doc} layer={active} />
      <div role="tree" aria-label="Layers" aria-multiselectable className="min-h-0 flex-1 overflow-y-auto" onDragLeave={(event) => !event.currentTarget.contains(event.relatedTarget as Node) && setDrop(null)}>
        {rows.map((row) => (
          <LayerRow
            key={row.layer.id}
            doc={doc}
            row={row}
            picked={picked.has(row.layer.id)}
            renaming={renaming === row.layer.id}
            onRename={setRenaming}
            collapsed={collapsed.has(row.layer.id)}
            onToggleCollapsed={() => toggleCollapsed(row.layer.id)}
            drop={drop?.id === row.layer.id ? drop.where : null}
            onDragOver={onDragOver}
            onDrop={onDrop}
          />
        ))}
        {!rows.length && <div className="p-4 text-center text-[12px] text-fg-3">No layers</div>}
      </div>
      <div className="flex h-9 shrink-0 items-center justify-end gap-0.5 border-t border-line px-1.5">
        {[
          { label: 'Clip to the layer below', icon: <IconCornerLeftDown size={15} />, run: () => toggleClipping(doc), disabled: !active || active.isGroup },
          { label: 'Add a mask', icon: <IconMask size={15} />, run: () => addMask(doc), disabled: !active || Boolean(active.mask) },
          { label: 'New folder', icon: <IconFolderPlus size={15} />, run: () => addFolder(doc) },
          { label: 'Duplicate', icon: <IconCopy size={15} />, run: () => duplicatePicked(doc), disabled: !active },
          { label: 'New layer', icon: <IconPlus size={15} />, run: () => addLayer(doc) },
          { label: 'Delete', icon: <IconTrash size={15} />, run: () => deletePicked(doc), disabled: !active }
        ].map((button) => (
          <button
            key={button.label}
            type="button"
            title={button.label}
            aria-label={button.label}
            disabled={button.disabled}
            onClick={button.run}
            className="grid size-7 place-items-center rounded-md text-fg-3 hover:bg-white/8 hover:text-fg disabled:opacity-35 disabled:hover:bg-transparent"
          >
            {button.icon}
          </button>
        ))}
      </div>
    </div>
  )
}
