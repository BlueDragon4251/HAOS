import { atom } from 'nanostores'
import type { DurableMission } from '../../shared/missions.ts'
import { refreshDurableMissions } from './durable-missions.ts'
import { focusMissions } from './missions.ts'

const PREFIX = 'haos.pending-message.'
const KEY = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
interface PendingMessage { key: string; digest: string; at: number }
export const $pendingMissionMessages = atom<PendingMessage[]>([])
let recovering: Promise<void> | null = null

function readPending(): PendingMessage[] {
  const rows: PendingMessage[] = []
  for (let index = 0; index < localStorage.length; index++) {
    const name = localStorage.key(index)
    if (!name?.startsWith(PREFIX)) continue
    const row = JSON.parse(localStorage.getItem(name) || 'null') as PendingMessage | null
    if (!row || !KEY.test(row.key) || name !== PREFIX + row.key || !/^[0-9a-f]{64}$/.test(row.digest) || !Number.isFinite(row.at)) {
      throw new Error('A pending message receipt needs inspection before submitting more work')
    }
    rows.push(row)
  }
  return rows.sort((a, b) => a.at - b.at)
}

function forget(key: string): void {
  localStorage.removeItem(PREFIX + key)
  $pendingMissionMessages.set(readPending())
}

function verifyReceipt(mission: DurableMission, key: string): void {
  if (!mission || !KEY.test(mission.id) || mission.idempotency_key !== key) {
    throw new Error('The controller returned an unverified message receipt')
  }
}

/** Recover a lost admission reply without replaying the prompt or creating any session. */
export function recoverMissionMessages(): Promise<void> {
  if (recovering) return recovering
  recovering = (async () => {
    const pending = readPending()
    $pendingMissionMessages.set(pending)
    for (const row of pending) {
      const mission = await window.heraldOS.missions.request('missions.lookup', { idempotency_key: row.key })
      if (mission) {
        verifyReceipt(mission, row.key)
        forget(row.key)
        focusMissions({ missionId: mission.id })
      }
    }
    await refreshDurableMissions()
  })().finally(() => { recovering = null })
  return recovering
}

/** Persist only a request ID and digest before sending; no chat or secret value enters browser storage. */
export async function submitMissionMessage(text: string, requestedKey?: string): Promise<DurableMission> {
  const goal = text.trim()
  if ((requestedKey && !KEY.test(requestedKey)) || !goal || goal.length > 32000) throw new Error('A message needs a valid request ID and a goal of at most 32000 characters')
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(goal)))].map(byte => byte.toString(16).padStart(2, '0')).join('')
  const pending = readPending()
  // Re-entering the exact text after a UI restart reuses its previous intent.
  // A restart itself performs lookup only and never sends a prompt.
  const key = requestedKey ?? pending.find(row => row.digest === digest)?.key ?? crypto.randomUUID()
  const old = pending.find(row => row.key === key)
  if (old && old.digest !== digest) throw new Error('The pending request belongs to a different message')
  if (pending.some(row => row.key !== key && row.digest === digest)) throw new Error('This message has an unresolved admission receipt; check it before creating another request')
  if (pending.length >= 32 && !old) throw new Error('Resolve pending message receipts before sending more work')
  localStorage.setItem(PREFIX + key, JSON.stringify(old ?? { key, digest, at: Date.now() }))
  $pendingMissionMessages.set(readPending())
  const mission = await window.heraldOS.missions.request('missions.create', { goal, idempotency_key: key })
  verifyReceipt(mission, key)
  forget(key)
  focusMissions({ missionId: mission.id })
  void refreshDurableMissions()
  return mission
}
