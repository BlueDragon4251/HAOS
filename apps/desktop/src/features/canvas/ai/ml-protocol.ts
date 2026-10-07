/* Messages between the window and the model worker. */

import type { MaskOptions } from './segment-math.ts'

export type MlRequest = { id: number } & (
  | { op: 'segment'; token: string; rgba: Uint8ClampedArray; width: number; height: number }
  | { op: 'salientMask'; token: string; width: number; height: number; options: Partial<MaskOptions> }
  | { op: 'encode'; key: string; rgba: Uint8ClampedArray; width: number; height: number }
  | { op: 'decode'; key: string; points: [number, number][]; labels: number[]; width: number; height: number }
  | { op: 'forget'; token: string }
)

export interface MlReply {
  id: number
  ok: boolean
  error?: string
  backend?: 'webgpu' | 'wasm'
  mask?: Uint8Array
  /** The size a picture was encoded at. */
  width?: number
  height?: number
}
