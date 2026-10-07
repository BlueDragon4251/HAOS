import {
  IconAdjustmentsHorizontal,
  IconBlur,
  IconBorderOuter,
  IconBulb,
  IconChartLine,
  IconColorFilter,
  IconContrast,
  IconContrast2,
  IconDots,
  IconDropletHalf2,
  IconGrain,
  IconPalette,
  IconShadow,
  IconSparkles,
  IconSquareHalf,
  IconSunHigh,
  IconWind
} from '@tabler/icons-react'
import type { AdjustmentKind, EffectKind } from '../../../shared/canvas/comp-format.ts'

type Icon = typeof IconBlur

/** An icon for each adjustment kind, shared by the Layers panel, the Properties panel and the menus. */
export const ADJUSTMENT_ICONS: Record<AdjustmentKind, Icon> = {
  'Hue/Saturation': IconDropletHalf2,
  Levels: IconAdjustmentsHorizontal,
  Curves: IconChartLine,
  Exposure: IconSunHigh,
  'Gradient Map': IconPalette,
  Grain: IconGrain,
  Invert: IconContrast,
  'Black & White': IconContrast2,
  'Color Balance': IconColorFilter,
  'Gaussian Blur': IconBlur,
  'Motion Blur': IconWind,
  'Add Noise': IconDots
}

export const EFFECT_ICONS: Record<EffectKind, Icon> = {
  stroke: IconBorderOuter,
  shadow: IconShadow,
  colorOverlay: IconSquareHalf,
  innerShadow: IconShadow,
  outerGlow: IconBulb,
  innerGlow: IconSparkles
}
