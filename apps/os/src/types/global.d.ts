import type { HermesOSApi } from '../../preload/index.ts'

declare global {
  interface Window {
    hermesOS: HermesOSApi
  }
}

export {}
