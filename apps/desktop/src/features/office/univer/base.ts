import '@univerjs/design/lib/index.css'
import '@univerjs/ui/lib/index.css'
import { LocaleType, LogLevel, mergeLocales, Univer } from '@univerjs/core'
import { FUniver } from '@univerjs/core/facade'
import DesignEnUS from '@univerjs/design/locale/en-US'
import { UniverRenderEnginePlugin } from '@univerjs/engine-render'
import UIEnUS from '@univerjs/ui/locale/en-US'
import { UniverUIPlugin } from '@univerjs/ui'
import { heraldUniverTheme } from './theme.ts'

/*
 * One Univer instance with its chrome in a Herald window. Univer keeps one palette and one
 * light-or-dark flag for the whole page (its theme is a style sheet on :root), so every Office
 * window takes Herald's current theme when it opens.
 */

export type Locales = Parameters<typeof mergeLocales>[0]

export interface EngineOptions {
  container: HTMLElement
  locales: Locales[]
  /** The ribbon and the menus Univer draws inside the window. */
  toolbar?: boolean
}

export function createUniver(options: EngineOptions): { univer: Univer; api: FUniver } {
  const { theme, darkMode } = heraldUniverTheme()
  const univer = new Univer({
    theme,
    darkMode,
    locale: LocaleType.EN_US,
    locales: { [LocaleType.EN_US]: mergeLocales(DesignEnUS, UIEnUS, ...options.locales) },
    logLevel: LogLevel.WARN
  })
  univer.registerPlugin(UniverRenderEnginePlugin)
  univer.registerPlugin(UniverUIPlugin, { container: options.container, header: options.toolbar !== false, toolbar: options.toolbar !== false, ribbonType: 'simple', footer: true, contextMenu: true })

  return { univer, api: FUniver.newAPI(univer) }
}
