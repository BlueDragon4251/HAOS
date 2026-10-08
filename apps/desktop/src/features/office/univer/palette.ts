import { fromHsl, isHexColor, mix, toHsl } from '../../../../shared/theme.ts'

/*
 * Univer's palette in Herald's colours. Univer reads one palette for its React chrome (as CSS
 * variables) and for the canvas it draws cells and pages on (as values), so it is worked out from
 * the theme's tokens when an Office window opens. Univer keeps a light ramp in both schemes (gray 0
 * is the lightest) and inverts canvas colours itself in dark mode, so the ramp stays light here.
 */

export type Shade = 50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900
export type Ramp = Record<Shade, string>
export type GrayRamp = Ramp & Record<0 | 1000, string>

const SHADES: readonly Shade[] = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]

/** How far each shade sits from the base colour: toward white below 600, toward black above it. */
const TOWARD: Record<Shade, number> = { 50: 0.93, 100: 0.86, 200: 0.72, 300: 0.55, 400: 0.3, 500: 0.14, 600: 0, 700: 0.16, 800: 0.3, 900: 0.42 }

/** A ramp whose 600 is `base`, the shade Univer uses for its own brand colour. */
export function rampOf(base: string): Ramp {
  const color = isHexColor(base) ? base : '#2f7dff'
  const ramp = {} as Ramp

  for (const shade of SHADES) {
    ramp[shade] = shade < 600 ? mix(color, '#ffffff', TOWARD[shade]) : mix(color, '#000000', TOWARD[shade])
  }

  return ramp
}

/** Lightness of each gray, lightest first, as Univer's default gray ramp has them. */
const GRAY_LIGHTNESS: Record<0 | Shade | 1000, number> = { 0: 1, 50: 0.975, 100: 0.94, 200: 0.9, 300: 0.7, 400: 0.54, 500: 0.36, 600: 0.22, 700: 0.17, 800: 0.13, 900: 0.11, 1000: 0 }

/** Grays tinted with the theme's background hue, so dark chrome reads as Herald's glass rather than neutral gray. */
export function grayRampOf(background: string, tint = 0.32): GrayRamp {
  const { h, s } = toHsl(isHexColor(background) ? background : '#050f33')
  const saturation = Math.min(0.6, s * tint)
  const ramp = {} as GrayRamp

  for (const key of [0, ...SHADES, 1000] as const) {
    const l = GRAY_LIGHTNESS[key]
    ramp[key] = l === 1 ? '#ffffff' : l === 0 ? '#000000' : fromHsl({ h, s: saturation, l })
  }

  return ramp
}

export interface HeraldTokens {
  accent: string
  background: string
}

/** The parts of Univer's palette Herald sets; the rest (reds, greens and so on) keep Univer's values. */
export function heraldPalette(tokens: HeraldTokens): { primary: Ramp; gray: GrayRamp } {
  return { primary: rampOf(tokens.accent), gray: grayRampOf(tokens.background) }
}
