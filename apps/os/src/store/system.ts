import { useStore } from '@nanostores/react'
import { atom } from 'nanostores'
import { useEffect } from 'react'
import type { SystemInfo, SystemStats } from '../../shared/ipc.ts'

export const $systemStats = atom<SystemStats | null>(null)
export const $systemInfo = atom<SystemInfo | null>(null)

let subscribers = 0
let unsubscribe: (() => void) | null = null

/** Reference-counted live stats: the sampler in main runs only while a mounted component wants it. */
export function useSystemStats(): SystemStats | null {
  useEffect(() => {
    subscribers++

    if (subscribers === 1) {
      unsubscribe = window.hermesOS.system.subscribeStats(stats => $systemStats.set(stats))
    }

    return () => {
      subscribers--

      if (subscribers === 0 && unsubscribe) {
        unsubscribe()
        unsubscribe = null
      }
    }
  }, [])

  return useStore($systemStats)
}

export function useSystemInfo(): SystemInfo | null {
  const info = useStore($systemInfo)

  useEffect(() => {
    if (!$systemInfo.get()) {
      void window.hermesOS.system.info().then(value => $systemInfo.set(value))
    }
  }, [])

  return info
}
