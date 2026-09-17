import { DarwinPlatform } from './darwin.ts'
import { GenericPlatform } from './generic.ts'
import type { HostPlatform } from './types.ts'

let instance: HostPlatform | null = null

export function hostPlatform(): HostPlatform {
  if (!instance) {
    instance = process.platform === 'darwin' ? new DarwinPlatform() : new GenericPlatform()
  }

  return instance
}

export type { EditorTarget, HostPlatform } from './types.ts'
