/** Version 1 of the local controller contract. Owner authority is absent from this surface. */
export type DurableMissionState = 'queued' | 'running' | 'waiting' | 'blocked' | 'failed' | 'completed' | 'cancelled'

export interface DurableMission {
  id: string
  actor: string
  goal: string
  state: DurableMissionState
  phase: string
  session_id: string | null
  stored_session_id: string | null
  created_at: number
  updated_at: number
  deadline: number
  attempt: number
  max_attempts: number
  cancel_requested: number
  error: string | null
  result: string | null
}

export interface MissionEvent {
  seq: number
  mission_id: string
  at: number
  kind: string
  payload: Record<string, unknown>
}

export interface MissionQuestion {
  id: string | number
  method: 'approval' | 'clarify'
  params: { session_id: string; description?: string; command?: string; choices?: string[]; [key: string]: unknown }
}

export interface MissionServiceHealth {
  service: 'haos-controller'
  backend_connected: boolean
  current_mission: string | null
  pending_requests: MissionQuestion[]
}

export interface MissionMethods {
  health: { params: Record<string, never>; result: MissionServiceHealth }
  'missions.list': { params: Record<string, never>; result: DurableMission[] }
  'missions.create': { params: { goal: string; idempotency_key: string; timeout?: number }; result: DurableMission }
  'missions.get': { params: { id: string }; result: DurableMission }
  'missions.events': { params: { id: string; after?: number }; result: MissionEvent[] }
  'missions.cancel': { params: { id: string }; result: DurableMission }
  'missions.answer': { params: { request_id: string; choice?: 'once' | 'deny'; answer?: string }; result: { accepted: boolean } }
}

export const MISSION_METHODS: ReadonlySet<string> = new Set(['health', 'missions.list', 'missions.create', 'missions.get', 'missions.events', 'missions.cancel', 'missions.answer'])
