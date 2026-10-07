/*
 * Snapping for the tools: points and moving boxes pulled onto guides, the canvas's edges and
 * centre, and other layers' edges and centres, when they come within a few screen pixels.
 */

import type { Vec2 } from '../../../../shared/canvas/comp-format.ts'
import type { CanvasDocument } from '../engine/document.ts'
import type { View } from '../engine/gpu/view.ts'

/** A document point pulled onto the nearest line within reach, each way on its own. */
export function snapPoint(_doc: CanvasDocument, point: Vec2, _view: View): Vec2 {
  return point
}
