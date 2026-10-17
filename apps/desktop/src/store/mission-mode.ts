import { atom } from 'nanostores'

/** Electron's fixed runtime mode; an unavailable controller never selects legacy execution. */
export const $managedMissions = atom<boolean | null>(null)
export const $missionModeError = atom<string | null>(null)
let resolving: Promise<boolean> | null = null

export function resolveMissionMode(): Promise<boolean> {
  const known = $managedMissions.get()
  if (known !== null) return Promise.resolve(known)
  if (!resolving) {
    resolving = Promise.resolve().then(() => window.heraldOS.missions.serviceInfo()).then(info => {
      if (typeof info.managed !== 'boolean') throw new Error('The runtime did not identify its mission mode')
      $managedMissions.set(info.managed)
      $missionModeError.set(null)
      return info.managed
    }).catch(error => {
      $missionModeError.set(error instanceof Error ? error.message : String(error))
      throw error
    }).finally(() => { resolving = null })
  }
  return resolving
}
