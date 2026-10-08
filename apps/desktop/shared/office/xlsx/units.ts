/*
 * Excel's sizes as Univer's pixels (at 96 dpi) and back. Row heights are points. Column widths are
 * characters of the default font's widest digit (7 pixels for Calibri or Arial at 11 points, the
 * fonts nearly every file uses), as the file format defines them: a width of 8.43 characters is 64
 * pixels, Excel's default column.
 */

export const DIGIT_WIDTH = 7

const PADDING = 5

export const pointsToPixels = (points: number): number => Math.round((points * 96) / 72)

export const pixelsToPoints = (pixels: number): number => Math.round(pixels * 0.75 * 100) / 100

/** A column width stored in a file (`<col width>`) as pixels. */
export function columnPixels(width: number): number {
  return Math.trunc(((256 * width + Math.trunc(128 / DIGIT_WIDTH)) / 256) * DIGIT_WIDTH)
}

/** Pixels as the width a file stores, to 1/256 of a character, which reads back as the same pixels. */
export function columnWidth(pixels: number): number {
  if (pixels <= PADDING) {
    return 0
  }

  const characters = Math.trunc(((pixels - PADDING) / DIGIT_WIDTH) * 100 + 0.5) / 100

  return Math.trunc(((characters * DIGIT_WIDTH + PADDING) / DIGIT_WIDTH) * 256) / 256
}

/** A sheet's default column in pixels, from `<sheetFormatPr>`: its default width, else its base width rounded up to 8 pixels. */
export function defaultColumnPixels(defaultColWidth?: number, baseColWidth = 8): number {
  if (defaultColWidth && defaultColWidth > 0) {
    return columnPixels(defaultColWidth)
  }

  return Math.ceil((baseColWidth * DIGIT_WIDTH + PADDING) / 8) * 8
}

/** Excel's own defaults: 15-point rows and 8.43-character columns. */
export const EXCEL_ROW_POINTS = 15
export const EXCEL_COLUMN_PIXELS = 64
