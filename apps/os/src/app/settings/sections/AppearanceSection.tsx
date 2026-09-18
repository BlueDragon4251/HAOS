import { useStore } from '@nanostores/react'
import { IconDroplet, IconLayoutBottombar, IconPhoto, IconSparkles, IconSunMoon } from '@tabler/icons-react'
import { Chips, GlassButton, Toggle } from '../../../components/ui/glass.tsx'
import { cn } from '../../../lib/cn.ts'
import { $prefs, updatePrefs } from '../../../store/backend.ts'
import { notify } from '../../../store/notifications.ts'
import { errorText, markSaved, SectionTitle, SettingsGroup, SettingsRow } from './shared.tsx'

const THEMES = [
  { id: 'ocean', label: 'Ocean' },
  { id: 'graphite', label: 'Graphite' }
] as const

const ACCENTS: { id: 'blue' | 'ice' | 'violet'; label: string; color: string }[] = [
  { id: 'blue', label: 'Blue', color: '#2f7dff' },
  { id: 'ice', label: 'Ice', color: '#4cc2ff' },
  { id: 'violet', label: 'Violet', color: '#7c6cff' }
]

export function AppearanceSection() {
  const prefs = useStore($prefs)

  const save = async (patch: Parameters<typeof updatePrefs>[0]) => {
    try {
      await updatePrefs(patch)
      markSaved()
    } catch (error) {
      notify({ title: 'Could not save setting', body: errorText(error), level: 'error' })
    }
  }

  const chooseWallpaper = async () => {
    try {
      const [path] = await window.hermesOS.fs.pickFiles({ directory: false, multiple: false })

      if (path) {
        await save({ wallpaper: `file://${path}` })
      }
    } catch (error) {
      notify({ title: 'Could not choose wallpaper', body: errorText(error), level: 'error' })
    }
  }

  const wallpaperName = prefs.wallpaper ? decodeURIComponent(prefs.wallpaper.replace(/^file:\/\//, '')).split('/').pop() : null

  return (
    <>
      <SectionTitle title="Appearance" subtitle="Theme, accent and wallpaper." />

      <SettingsGroup title="Look">
        <SettingsRow icon={<IconSunMoon />} label="Theme" description="Ocean is the deep-blue glass. Graphite is the darker preset." keywords="dark colour color">
          <Chips items={THEMES} value={prefs.theme} onChange={theme => void save({ theme })} />
        </SettingsRow>
        <SettingsRow icon={<IconDroplet />} label="Accent" description="The single accent colour used across the environment." keywords="colour color highlight">
          <div className="flex items-center gap-2" role="radiogroup" aria-label="Accent colour">
            {ACCENTS.map(accent => {
              const active = prefs.accent === accent.id

              return (
                <button
                  key={accent.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  aria-label={accent.label}
                  onClick={() => void save({ accent: accent.id })}
                  className={cn('size-6 rounded-full border border-white/30 transition-transform', active ? 'scale-110 shadow-[0_0_0_2px_var(--color-bg),0_0_0_3.5px_var(--color-fg-3)]' : 'opacity-75 hover:opacity-100')}
                  style={{ background: accent.color }}
                />
              )
            })}
          </div>
        </SettingsRow>
        <SettingsRow icon={<IconPhoto />} label="Wallpaper" description={wallpaperName ? <span className="selectable">{wallpaperName}</span> : 'The living Hermes wallpaper.'} keywords="background image desktop">
          {prefs.wallpaper && (
            <GlassButton size="sm" variant="ghost" onClick={() => void save({ wallpaper: '' })} aria-label="Use Hermes wallpaper">
              Use Hermes wallpaper
            </GlassButton>
          )}
          <GlassButton size="sm" onClick={() => void chooseWallpaper()} aria-label="Choose wallpaper image">
            Choose image…
          </GlassButton>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="Dock">
        <SettingsRow icon={<IconLayoutBottombar />} label="Automatically hide the Dock" description="The Dock slides away and returns when the cursor reaches the bottom edge." keywords="dock autohide hide show">
          <Toggle checked={prefs.dockAutoHide !== false} onChange={next => void save({ dockAutoHide: next })} label="Automatically hide the Dock" />
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="Motion">
        <SettingsRow icon={<IconSparkles />} label="Reduce motion" description="Collapse non-essential animation across the shell." keywords="animation accessibility">
          <Toggle checked={prefs.reduceMotion} onChange={next => void save({ reduceMotion: next })} label="Reduce motion" />
        </SettingsRow>
      </SettingsGroup>
    </>
  )
}
