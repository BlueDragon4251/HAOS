import { atom } from 'nanostores'
import type { DurableMission, MissionEvent, MissionServiceHealth } from '../../shared/missions.ts'

export const $durableMissions = atom<DurableMission[]>([])
export const $missionServiceHealth = atom<MissionServiceHealth | null>(null)
export const $missionServiceError = atom<string | null>(null)
export const $missionEvents = atom<Record<string, MissionEvent[]>>({})
let refreshInFlight: Promise<void> | null = null
const eventsInFlight = new Map<string, Promise<void>>()

export function refreshDurableMissions(): Promise<void> {
  if (refreshInFlight) return refreshInFlight
  refreshInFlight = (async () => {
    try {
      const [health, missions] = await Promise.all([
        window.heraldOS.missions.request('health', {}), window.heraldOS.missions.request('missions.list', {})
      ])
      $missionServiceHealth.set(health)
      $durableMissions.set(missions)
      $missionServiceError.set(null)
    } catch (error) {
      $missionServiceHealth.set(null)
      $missionServiceError.set(error instanceof Error ? error.message : String(error))
    }
  })().finally(() => { refreshInFlight = null })
  return refreshInFlight
}

export function loadMissionEvents(id: string): Promise<void> {
  const inFlight = eventsInFlight.get(id)
  if (inFlight) return inFlight
  const request = loadEvents(id).finally(() => { eventsInFlight.delete(id) })
  eventsInFlight.set(id, request)
  return request
}

async function loadEvents(id: string): Promise<void> {
  const old = $missionEvents.get()[id] ?? []
  const after = old.at(-1)?.seq ?? 0
  const next = await window.heraldOS.missions.request('missions.events', { id, after })
  if (next.length) {
    const unique = new Map([...($missionEvents.get()[id] ?? []), ...next].map(event => [event.seq, event]))
    $missionEvents.set({ ...$missionEvents.get(), [id]: [...unique.values()].sort((a, b) => a.seq - b.seq).slice(-500) })
  }
}

export async function cancelDurableMission(id: string): Promise<void> {
  await window.heraldOS.missions.request('missions.cancel', { id })
  await refreshDurableMissions()
}

export async function pauseDurableMission(id: string): Promise<void> {
  await window.heraldOS.missions.request('missions.pause', { id })
  await refreshDurableMissions()
}

export async function resumeDurableMission(id: string): Promise<DurableMission> {
  const mission = await window.heraldOS.missions.request('missions.resume', { id })
  await refreshDurableMissions()
  return mission
}

export async function answerMissionRequest(requestId: string, choice?: 'once' | 'deny', answer?: string): Promise<void> {
  await window.heraldOS.missions.request('missions.answer', { request_id: requestId, choice, answer })
  await refreshDurableMissions()
}
