import { useStore } from '@nanostores/react'
import {
  IconAlignCenter,
  IconAlignLeft,
  IconAlignRight,
  IconCheck,
  IconCircle,
  IconItalic,
  IconLayersIntersect,
  IconLayersSubtract,
  IconLayersUnion,
  IconLine,
  IconSquare,
  IconSquareRounded,
  IconSquareToggle,
  IconX
} from '@tabler/icons-react'
import { atom } from 'nanostores'
import { useEffect, useState } from 'react'
import { RANGES, type TextAlignment } from '../../../shared/canvas/comp-format.ts'
import { GlassButton } from '../../components/ui/glass.tsx'
import { cn } from '../../lib/cn.ts'
import { cssOf, type RGB } from './color.ts'
import { ColorPicker } from './ColorPicker.tsx'
import type { CanvasDocument } from './engine/document.ts'
import type { SelectionMode } from './engine/selection.ts'
import { useRevision } from './hooks.ts'
import { applyCrop, cancelCrop, $crop, cropRect } from './tools/crop.ts'
import {
  $autoSelect,
  $brush,
  $bucket,
  $eraser,
  $eyedropper,
  $foreground,
  $gradient,
  $marquee,
  $selectionMode,
  $shape,
  $showTransform,
  $tool,
  $type,
  $wand,
  type BrushOptions,
  type ShapeTool,
  toolDef,
  type TypeOptions
} from './tools/state.ts'
import { paintsMask } from './tools/target.ts'
import { $transform, cancelTransform, commitTransform, sessionFor } from './tools/transform.ts'
import { $typing, applyTypeOptions, cancelTyping, commitTyping, optionsFrom } from './tools/type.ts'
import { actualPixels, fitToScreen } from './view-state.ts'

const stop = (event: React.KeyboardEvent) => {
  if (event.key === 'Enter') {
    ;(event.target as HTMLInputElement).blur()
  }

  event.stopPropagation()
}

/** A small labelled number field; it takes a value only when it is a number in range. */
function NumberField({ label, value, onChange, min = 0, max = 10_000, step = 1, unit, width = 'w-14', title }: { label: string; value: number; onChange: (value: number) => void; min?: number; max?: number; step?: number; unit?: string; width?: string; title?: string }) {
  const [draft, setDraft] = useState(String(value))

  useEffect(() => setDraft(String(Math.round(value * 100) / 100)), [value])

  return (
    <label className="flex items-center gap-1.5 text-fg-3" title={title}>
      {label}
      <input
        type="number"
        value={draft}
        min={min}
        max={max}
        step={step}
        onChange={(event) => {
          setDraft(event.target.value)
          const number = Number(event.target.value)

          if (event.target.value !== '' && Number.isFinite(number) && number >= min && number <= max) {
            onChange(number)
          }
        }}
        onBlur={() => setDraft(String(Math.round(value * 100) / 100))}
        onKeyDown={stop}
        className={cn('glass-input h-6 rounded-md px-1.5 text-[12px] text-fg tabular-nums outline-none', width)}
      />
      {unit && <span>{unit}</span>}
    </label>
  )
}

/** A 0 to 1 setting shown as a percentage. */
const Percent = ({ label, value, onChange, title }: { label: string; value: number; onChange: (value: number) => void; title?: string }) => (
  <NumberField label={label} title={title} value={Math.round(value * 100)} min={0} max={100} unit="%" width="w-12" onChange={(percent) => onChange(percent / 100)} />
)

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex items-center gap-1.5">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  )
}

function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (value: T) => void; options: { id: T; label: string; icon?: React.ReactNode }[]; label: string }) {
  return (
    <div className="flex items-center rounded-md bg-white/5 p-0.5 ring-1 ring-line" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="radio"
          aria-checked={value === option.id}
          title={option.label}
          aria-label={option.label}
          onClick={() => onChange(option.id)}
          className={cn('grid h-5 min-w-6 place-items-center rounded px-1 text-[11.5px]', value === option.id ? 'bg-white/14 text-fg' : 'text-fg-3 hover:text-fg')}
        >
          {option.icon ?? option.label}
        </button>
      ))}
    </div>
  )
}

const MODES: { id: SelectionMode; label: string; icon: React.ReactNode }[] = [
  { id: 'new', label: 'New selection', icon: <IconSquare size={13} /> },
  { id: 'add', label: 'Add to the selection (Shift)', icon: <IconLayersUnion size={13} /> },
  { id: 'subtract', label: 'Take away from the selection (Alt)', icon: <IconLayersSubtract size={13} /> },
  { id: 'intersect', label: 'Intersect with the selection (Shift+Alt)', icon: <IconLayersIntersect size={13} /> }
]

function SelectionModes() {
  const mode = useStore($selectionMode)

  return <Segmented label="Selection mode" value={mode} onChange={(next) => $selectionMode.set(next)} options={MODES} />
}

const patch = <T extends object>(store: { get(): T; set(value: T): void }, change: Partial<T>) => store.set({ ...store.get(), ...change })

function BrushFields({ store, doc }: { store: typeof $brush; doc: CanvasDocument }) {
  const options = useStore(store) as BrushOptions
  const set = (change: Partial<BrushOptions>) => patch(store, change)

  return (
    <>
      <NumberField label="Size" title="Size ([ and ])" value={options.size} min={1} max={5000} unit="px" onChange={(size) => set({ size })} />
      <Percent label="Hardness" title="Hardness (Shift+[ and Shift+])" value={options.hardness} onChange={(hardness) => set({ hardness })} />
      <Percent label="Opacity" title="Opacity (number keys)" value={options.opacity} onChange={(opacity) => set({ opacity })} />
      <Percent label="Flow" value={options.flow} onChange={(flow) => set({ flow })} />
      <NumberField label="Spacing" value={Math.round(options.spacing * 100)} min={1} max={200} unit="%" width="w-12" onChange={(spacing) => set({ spacing: spacing / 100 })} />
      {paintsMask(doc) && <span className="rounded-full bg-white/8 px-2 py-0.5 text-[11px] text-fg-2">On the mask</span>}
    </>
  )
}

/** Font families on this computer, listed once. */
const $fonts = atom<string[] | null>(null)

function loadFonts(): void {
  if (!$fonts.get()) {
    $fonts.set([])
    window.heraldOS.fonts
      .list()
      .then((families) => $fonts.set(families))
      .catch(() => {})
  }
}

const WEIGHTS: { value: number; label: string }[] = [
  { value: 100, label: 'Thin' },
  { value: 200, label: 'Extra Light' },
  { value: 300, label: 'Light' },
  { value: 400, label: 'Regular' },
  { value: 500, label: 'Medium' },
  { value: 600, label: 'Semibold' },
  { value: 700, label: 'Bold' },
  { value: 800, label: 'Extra Bold' },
  { value: 900, label: 'Black' }
]

function TypeFields({ doc }: { doc: CanvasDocument }) {
  const options = useStore($type)
  const typing = useStore($typing)
  const foreground = useStore($foreground)
  const fonts = useStore($fonts)
  const [picking, setPicking] = useState(false)
  const [family, setFamily] = useState(options.family)
  const session = typing?.docKey === doc.key ? typing : null
  const layer = !session && doc.active?.text ? doc.active : null
  const style = session?.style ?? layer?.text
  const colour: RGB = style ? [Math.round(style.red * 255), Math.round(style.green * 255), Math.round(style.blue * 255)] : foreground

  useEffect(loadFonts, [])
  useEffect(() => setFamily(options.family), [options.family])

  // A text layer picked with the Type tool in hand shows its own style here.
  const picked = layer?.text

  useEffect(() => {
    if (picked) {
      $type.set(optionsFrom(picked))
    }
  }, [picked])

  const set = (change: Partial<TypeOptions>) => {
    const next = { ...$type.get(), ...change }
    $type.set(next)

    if (session || layer) {
      applyTypeOptions(doc, next)
    }
  }

  // A family takes effect once it is picked from the list, or typed and confirmed.
  const takeFamily = (value: string) => {
    const name = value.trim()

    if (name && name !== $type.get().family) {
      set({ family: name })
    }
  }

  return (
    <>
      <label className="flex items-center gap-1.5 text-fg-3">
        Font
        <input
          list="herald-canvas-fonts"
          value={family}
          onChange={(event) => {
            setFamily(event.target.value)

            if (fonts?.includes(event.target.value)) {
              takeFamily(event.target.value)
            }
          }}
          onBlur={() => takeFamily(family)}
          onKeyDown={stop}
          className="glass-input h-6 w-36 rounded-md px-1.5 text-[12px] text-fg outline-none"
        />
        <datalist id="herald-canvas-fonts">
          {(fonts ?? []).map((family) => (
            <option key={family} value={family} />
          ))}
        </datalist>
      </label>
      <select aria-label="Weight" value={options.weight} onChange={(event) => set({ weight: Number(event.target.value) })} className="glass-input h-6 rounded-md px-1 text-[12px] text-fg outline-none">
        {WEIGHTS.map((weight) => (
          <option key={weight.value} value={weight.value}>
            {weight.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        title="Italic"
        aria-label="Italic"
        aria-pressed={options.italic}
        onClick={() => set({ italic: !options.italic })}
        className={cn('grid size-6 place-items-center rounded-md ring-1 ring-line', options.italic ? 'bg-white/14 text-fg' : 'text-fg-3 hover:text-fg')}
      >
        <IconItalic size={13} />
      </button>
      <NumberField label="Size" value={options.size} min={RANGES.fontSize[0]} max={RANGES.fontSize[1]} unit="px" onChange={(size) => set({ size })} />
      <div className="relative">
        <button type="button" title="Text colour" aria-label="Text colour" onClick={() => setPicking(true)} className="block size-6 rounded-md ring-1 ring-white/40" style={{ background: cssOf(colour) }} />
        {picking && (
          <ColorPicker
            title="Text colour"
            colour={colour}
            onChange={(next) => {
              if (session || layer) {
                applyTypeOptions(doc, $type.get(), next)
              } else {
                $foreground.set(next)
              }
            }}
            onClose={() => setPicking(false)}
            className="top-full left-0 mt-2"
          />
        )}
      </div>
      <Segmented<TextAlignment>
        label="Alignment"
        value={options.alignment}
        onChange={(alignment) => set({ alignment })}
        options={[
          { id: 'Left', label: 'Align left', icon: <IconAlignLeft size={13} /> },
          { id: 'Center', label: 'Centre', icon: <IconAlignCenter size={13} /> },
          { id: 'Right', label: 'Align right', icon: <IconAlignRight size={13} /> }
        ]}
      />
      <NumberField label="Tracking" title="Extra space between letters" value={options.tracking} min={RANGES.tracking[0]} max={RANGES.tracking[1]} step={0.5} unit="px" width="w-12" onChange={(tracking) => set({ tracking })} />
      <NumberField label="Leading" title="Line spacing, baseline to baseline (0 is automatic: 120% of the size)" value={options.leading} min={RANGES.leading[0]} max={RANGES.leading[1]} step={1} unit="px" width="w-12" onChange={(leading) => set({ leading })} />
      {session && <Confirm onApply={() => void commitTyping(doc)} onCancel={cancelTyping} />}
    </>
  )
}

function Confirm({ onApply, onCancel }: { onApply: () => void; onCancel: () => void }) {
  return (
    <div className="ml-auto flex items-center gap-1">
      <button type="button" title="Cancel (Esc)" aria-label="Cancel" onClick={onCancel} className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-white/8 hover:text-fg">
        <IconX size={15} />
      </button>
      <button type="button" title="Apply (Enter)" aria-label="Apply" onClick={onApply} className="grid size-6 place-items-center rounded-md bg-accent/25 text-fg hover:bg-accent/40">
        <IconCheck size={15} />
      </button>
    </div>
  )
}

function MoveFields({ doc }: { doc: CanvasDocument }) {
  const autoSelect = useStore($autoSelect)
  const showTransform = useStore($showTransform)
  useStore($transform)
  const session = sessionFor(doc)

  if (session && !session.transient) {
    const { frame } = session

    return (
      <>
        <span className="text-fg-2">{session.quad ? 'Distort: drag the corners' : session.distort ? 'Distort: drag a corner, or the frame' : 'Free Transform'}</span>
        {!session.quad && (
          <span className="tabular-nums text-fg-3">
            {Math.round(frame.size[0])} × {Math.round(frame.size[1])} px · {Math.round(frame.rotation * 10) / 10}°
          </span>
        )}
        <span className="text-fg-3">Shift keeps proportions, Alt scales from the centre, ⌘-drag a corner distorts.</span>
        <Confirm onApply={() => commitTransform(doc)} onCancel={() => cancelTransform(doc)} />
      </>
    )
  }

  return (
    <>
      <Check label="Pick the layer under the pointer" checked={autoSelect} onChange={(checked) => $autoSelect.set(checked)} />
      <Check label="Show transform controls" checked={showTransform} onChange={(checked) => $showTransform.set(checked)} />
    </>
  )
}

function CropFields({ doc }: { doc: CanvasDocument }) {
  useStore($crop)
  const rect = cropRect(doc)

  return (
    <>
      <span className="tabular-nums text-fg-2">
        {rect.width} × {rect.height} px
      </span>
      <span className="text-fg-3">Drag the handles or a new box; layers keep their pixels.</span>
      <Confirm onApply={() => applyCrop(doc)} onCancel={cancelCrop} />
    </>
  )
}

const SHAPES: { id: ShapeTool; label: string; icon: React.ReactNode }[] = [
  { id: 'rectangle', label: 'Rectangle', icon: <IconSquare size={13} /> },
  { id: 'rounded', label: 'Rounded rectangle', icon: <IconSquareRounded size={13} /> },
  { id: 'ellipse', label: 'Ellipse', icon: <IconCircle size={13} /> },
  { id: 'line', label: 'Line', icon: <IconLine size={13} /> }
]

export function OptionsBar({ doc }: { doc: CanvasDocument }) {
  useRevision(doc)
  const tool = useStore($tool)
  const marquee = useStore($marquee)
  const wand = useStore($wand)
  const bucket = useStore($bucket)
  const gradient = useStore($gradient)
  const eyedropper = useStore($eyedropper)
  const shape = useStore($shape)

  return (
    <div className="flex h-9 shrink-0 items-center gap-3 overflow-x-auto border-b border-line px-3 text-[12px] whitespace-nowrap text-fg-2">
      <span className="text-fg-3">{toolDef(tool).label}</span>
      {tool === 'move' && <MoveFields doc={doc} />}
      {(tool === 'marquee' || tool === 'ellipse-marquee') && (
        <>
          <SelectionModes />
          <NumberField label="Feather" value={marquee.feather} min={0} max={1000} unit="px" width="w-12" onChange={(feather) => $marquee.set({ feather })} />
        </>
      )}
      {(tool === 'lasso' || tool === 'polygon-lasso') && (
        <>
          <SelectionModes />
          {tool === 'polygon-lasso' && <span className="text-fg-3">Click the corners; Enter or a double-click closes it, Backspace takes a corner back.</span>}
        </>
      )}
      {tool === 'wand' && (
        <>
          <SelectionModes />
          <NumberField label="Tolerance" value={wand.tolerance} min={0} max={255} width="w-12" onChange={(tolerance) => patch($wand, { tolerance })} />
          <Check label="Contiguous" checked={wand.contiguous} onChange={(contiguous) => patch($wand, { contiguous })} />
          <Check label="All layers" checked={wand.allLayers} onChange={(allLayers) => patch($wand, { allLayers })} />
        </>
      )}
      {tool === 'crop' && <CropFields doc={doc} />}
      {tool === 'eyedropper' && (
        <Segmented
          label="Sample"
          value={eyedropper.allLayers ? 'all' : 'layer'}
          onChange={(value) => $eyedropper.set({ allLayers: value === 'all' })}
          options={[
            { id: 'all', label: 'All layers' },
            { id: 'layer', label: 'Current layer' }
          ]}
        />
      )}
      {tool === 'brush' && <BrushFields store={$brush} doc={doc} />}
      {tool === 'eraser' && <BrushFields store={$eraser} doc={doc} />}
      {tool === 'bucket' && (
        <>
          <NumberField label="Tolerance" value={bucket.tolerance} min={0} max={255} width="w-12" onChange={(tolerance) => patch($bucket, { tolerance })} />
          <Check label="Contiguous" checked={bucket.contiguous} onChange={(contiguous) => patch($bucket, { contiguous })} />
          <Check label="All layers" checked={bucket.allLayers} onChange={(allLayers) => patch($bucket, { allLayers })} />
          <Percent label="Opacity" value={bucket.opacity} onChange={(opacity) => patch($bucket, { opacity })} />
        </>
      )}
      {tool === 'gradient' && (
        <>
          <Segmented
            label="Gradient"
            value={gradient.kind}
            onChange={(kind) => patch($gradient, { kind })}
            options={[
              { id: 'linear', label: 'Linear' },
              { id: 'radial', label: 'Radial' }
            ]}
          />
          <Segmented
            label="Colours"
            value={gradient.toTransparent ? 'transparent' : 'background'}
            onChange={(value) => patch($gradient, { toTransparent: value === 'transparent' })}
            options={[
              { id: 'background', label: 'To background' },
              { id: 'transparent', label: 'To transparent' }
            ]}
          />
          <button
            type="button"
            title="Reverse"
            aria-label="Reverse"
            aria-pressed={gradient.reverse}
            onClick={() => patch($gradient, { reverse: !gradient.reverse })}
            className={cn('grid size-6 place-items-center rounded-md ring-1 ring-line', gradient.reverse ? 'bg-white/14 text-fg' : 'text-fg-3 hover:text-fg')}
          >
            <IconSquareToggle size={13} />
          </button>
          <Percent label="Opacity" value={gradient.opacity} onChange={(opacity) => patch($gradient, { opacity })} />
        </>
      )}
      {tool === 'type' && <TypeFields doc={doc} />}
      {tool === 'shape' && (
        <>
          <Segmented label="Shape" value={shape.kind} onChange={(kind) => patch($shape, { kind })} options={SHAPES} />
          {shape.kind === 'rounded' && <NumberField label="Radius" value={shape.radius} min={0} max={5000} unit="px" width="w-12" onChange={(radius) => patch($shape, { radius })} />}
          {shape.kind === 'line' && <NumberField label="Width" value={shape.lineWidth} min={1} max={1000} unit="px" width="w-12" onChange={(lineWidth) => patch($shape, { lineWidth })} />}
          <span className="text-fg-3">In the foreground colour; Shift squares, Alt draws from the centre.</span>
        </>
      )}
      {(tool === 'zoom' || tool === 'hand') && (
        <div className="flex items-center gap-1.5">
          <GlassButton size="sm" variant="ghost" onClick={() => fitToScreen(doc)}>
            Fit on screen
          </GlassButton>
          <GlassButton size="sm" variant="ghost" onClick={() => actualPixels(doc)}>
            100%
          </GlassButton>
        </div>
      )}
    </div>
  )
}
