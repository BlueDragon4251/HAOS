import { defaultTheme } from '@univerjs/themes'
import { heraldPalette } from './palette.ts'

export type UniverTheme = typeof defaultTheme

const token = (style: CSSStyleDeclaration, name: string, fallback: string): string => style.getPropertyValue(name).trim() || fallback

/** Univer's palette and scheme from the page's current Herald theme. */
export function heraldUniverTheme(): { theme: UniverTheme; darkMode: boolean } {
  const style = getComputedStyle(document.documentElement)
  const { primary, gray } = heraldPalette({ accent: token(style, '--color-accent', '#2f7dff'), background: token(style, '--color-bg', '#050f33') })
  const scheme = style.colorScheme || token(style, 'color-scheme', 'dark')

  return { theme: { ...defaultTheme, primary, gray }, darkMode: !scheme.includes('light') }
}
