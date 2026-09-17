import { useStore } from '@nanostores/react'
import { IconFolder, IconMaximize, IconPower, IconStack2 } from '@tabler/icons-react'
import { GlassButton, Toggle } from '../../../components/ui/glass.tsx'
import { $prefs, updatePrefs } from '../../../store/backend.ts'
import { notify } from '../../../store/notifications.ts'
import { $spaces } from '../../../store/spaces.ts'
import { errorText, markSaved, MenuDropdown, SectionTitle, SettingsGroup, SettingsRow } from './shared.tsx'

export function GeneralSection() {
  const prefs = useStore($prefs)
  const spaces = useStore($spaces)
  const activeSpace = spaces.find(space => space.id === prefs.activeSpace) ?? spaces[0]

  const save = async (patch: Parameters<typeof updatePrefs>[0]) => {
    try {
      await updatePrefs(patch)
      markSaved()
    } catch (error) {
      notify({ title: 'Could not save setting', body: errorText(error), level: 'error' })
    }
  }

  const chooseFolder = async () => {
    try {
      const [path] = await window.hermesOS.fs.pickFiles({ directory: true })

      if (path) {
        await save({ defaultCwd: path })
      }
    } catch (error) {
      notify({ title: 'Could not choose folder', body: errorText(error), level: 'error' })
    }
  }

  return (
    <>
      <SectionTitle title="General" subtitle="How Hermes OS starts and where it works." />

      <SettingsGroup title="Startup">
        <SettingsRow icon={<IconMaximize />} label="Launch fullscreen" description="Hermes OS takes over the screen when it starts. Cmd+Ctrl+F toggles at any time." keywords="full screen start">
          <Toggle checked={prefs.fullscreenOnLaunch} onChange={next => void save({ fullscreenOnLaunch: next })} label="Launch fullscreen" />
        </SettingsRow>
        <SettingsRow icon={<IconStack2 />} label="Default Space" description="The Space Hermes OS opens in.">
          <MenuDropdown
            ariaLabel="Default Space"
            label={
              <span className="flex items-center gap-2">
                <span className="size-2 rounded-full" style={{ background: activeSpace?.color }} />
                {activeSpace?.name ?? 'Personal'}
              </span>
            }
            value={activeSpace?.id}
            items={spaces.map(space => ({
              id: space.id,
              label: (
                <span className="flex items-center gap-2">
                  <span className="size-2 rounded-full" style={{ background: space.color }} />
                  {space.name}
                </span>
              )
            }))}
            onSelect={id => void save({ activeSpace: id })}
          />
        </SettingsRow>
        <SettingsRow icon={<IconFolder />} label="Default folder" description={<span className="selectable font-mono text-[11.5px]">{prefs.defaultCwd || '~'}</span>} keywords="working directory cwd">
          <GlassButton size="sm" onClick={() => void chooseFolder()} aria-label="Choose default folder">
            Choose…
          </GlassButton>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="Session">
        <SettingsRow icon={<IconPower />} label="Quit Hermes OS" description="Stops the Hermes backend this shell started and returns to macOS." keywords="exit close">
          <GlassButton size="sm" variant="danger" onClick={() => void window.hermesOS.window.quit()} aria-label="Quit Hermes OS">
            Quit
          </GlassButton>
        </SettingsRow>
      </SettingsGroup>
    </>
  )
}
