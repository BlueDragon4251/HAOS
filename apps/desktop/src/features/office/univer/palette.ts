import { fromHsl, isHexColor, mix, parseHex, toHex, toHsl } from '../../../../shared/theme.ts'

/*
 * Univer's palette in Herald's colours. Univer reads one palette for its React chrome (as CSS
 * variables, the same for every instance on the page) and for the canvas it draws cells on. Its
 * ramps run light to dark (gray 0 is the lightest) in both schemes: in dark mode the chrome uses the
 * dark shades as they are, and the canvas draws with the light shades put through a fixed colour
 * matrix that turns light into dark. So for a dark Herald theme the light shades are worked out
 * backwards, as the colours the matrix turns into Herald's navy.
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

/** Univer's dark-mode matrix for canvas colours (invertColorByMatrix in @univerjs/core): each channel becomes 0.333 × itself − 0.667 × the other two + 1, clamped. */
const OFF_DIAGONAL = -0.667
const DIAGONAL = 0.333

export function invertForDarkMode(color: string): string {
  const { r, g, b } = parseHex(color) ?? { r: 0, g: 0, b: 0 }
  const [x, y, z] = [r / 255, g / 255, b / 255]
  const channel = (own: number, a: number, c: number) => Math.min(1, Math.max(0, DIAGONAL * own + OFF_DIAGONAL * (a + c) + 1)) * 255

  return toHex({ r: channel(x, y, z), g: channel(y, x, z), b: channel(z, x, y) })
}

/** The colour Univer's dark mode turns into `dark`: the matrix run backwards. */
export function beforeDarkMode(dark: string): string {
  const { r, g, b } = parseHex(dark) ?? { r: 0, g: 0, b: 0 }
  const d = [r / 255 - 1, g / 255 - 1, b / 255 - 1]
  // The matrix is I + bJ (b = -0.667, J all ones), whose inverse is I - (b / (1 + 3b)) J.
  const k = OFF_DIAGONAL / (1 + 3 * OFF_DIAGONAL)
  const sum = d[0] + d[1] + d[2]
  const [x, y, z] = d.map((value) => Math.min(1, Math.max(0, value - k * sum)) * 255)

  return toHex({ r: x, g: y, b: z })
}

/** Lightness of each gray, lightest first, as Univer's default gray ramp has them. */
const LIGHT_GRAYS: Record<0 | Shade | 1000, number> = { 0: 1, 50: 0.975, 100: 0.94, 200: 0.9, 300: 0.7, 400: 0.54, 500: 0.36, 600: 0.22, 700: 0.17, 800: 0.13, 900: 0.11, 1000: 0 }

/** Grays for a light theme, tinted with its background's hue. */
export function lightGrayRamp(background: string): GrayRamp {
  const { h, s } = toHsl(isHexColor(background) ? background : '#f4f6fb')
  const saturation = Math.min(0.4, s * 0.3)
  const ramp = {} as GrayRamp

  for (const key of [0, ...SHADES, 1000] as const) {
    const l = LIGHT_GRAYS[key]
    ramp[key] = l === 1 ? '#ffffff' : l === 0 ? '#000000' : fromHsl({ h, s: saturation, l })
  }

  return ramp
}

/** What the canvas draws for each light shade in dark mode (cells, headers, grid lines), and the dark chrome's own shades, as lightness and saturation. */
const DARK_CANVAS: Record<0 | 50 | 100 | 200 | 300 | 400, [number, number]> = { 0: [0.11, 0.62], 50: [0.13, 0.58], 100: [0.15, 0.55], 200: [0.22, 0.45], 300: [0.45, 0.3], 400: [0.58, 0.26] }
const DARK_CHROME: Record<500 | 600 | 700 | 800 | 900, [number, number]> = { 500: [0.42, 0.28], 600: [0.27, 0.42], 700: [0.2, 0.5], 800: [0.15, 0.56], 900: [0.12, 0.6] }

/** Grays for a dark theme: the canvas lands on the theme's navy and the chrome is that navy. */
export function darkGrayRamp(background: string): GrayRamp {
  const { h } = toHsl(isHexColor(background) ? background : '#050f33')
  const ramp = { 1000: '#000000' } as GrayRamp

  for (const [key, [l, s]] of Object.entries(DARK_CANVAS)) {
    ramp[Number(key) as 0 | Shade] = beforeDarkMode(fromHsl({ h, s, l }))
  }

  for (const [key, [l, s]] of Object.entries(DARK_CHROME)) {
    ramp[Number(key) as Shade] = fromHsl({ h, s, l })
  }

  return ramp
}

export interface HeraldTokens {
  accent: string
  background: string
  dark: boolean
}

/** The parts of Univer's palette Herald sets; the rest (reds, greens and so on) keep Univer's values. */
export function heraldPalette(tokens: HeraldTokens): { primary: Ramp; gray: GrayRamp } {
  return { primary: rampOf(tokens.accent), gray: tokens.dark ? darkGrayRamp(tokens.background) : lightGrayRamp(tokens.background) }
}
