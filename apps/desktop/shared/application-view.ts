import type { PrivateApplicationObservation, PrivateApplicationSnapshot } from './missions.ts'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const fields = (value: object, expected: string[]) => Object.keys(value).sort().join('|') === [...expected].sort().join('|')
const time = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0

export function applicationSnapshot(value: unknown, mission: string): PrivateApplicationSnapshot {
  if (!value || typeof value !== 'object') throw new Error('Application observation unavailable')
  const snapshot = value as PrivateApplicationSnapshot
  if (!fields(snapshot, ['mission', 'snapshot_at', 'mission_active', 'authority_available', 'applications']) || snapshot.mission !== mission || !UUID.test(mission) || !time(snapshot.snapshot_at) || typeof snapshot.mission_active !== 'boolean' || typeof snapshot.authority_available !== 'boolean' || !Array.isArray(snapshot.applications) || snapshot.applications.length > 4) throw new Error('Invalid mission application observation')
  const seen = new Set<string>()
  for (const app of snapshot.applications) {
    if (!app || typeof app !== 'object' || !fields(app, ['instance', 'program', 'admitted_at', 'observed_at', 'running', 'windows', 'capture_at', 'capture_sha256', 'jpeg']) || !UUID.test(app.instance) || seen.has(app.instance) || !/^[a-z][a-z0-9-]{0,47}$/.test(app.program) || !time(app.admitted_at) || app.admitted_at > snapshot.snapshot_at + 1) throw new Error('Invalid private application identity')
    seen.add(app.instance)
    if (app.observed_at === null ? app.running !== null || app.windows !== null : !time(app.observed_at) || app.observed_at > snapshot.snapshot_at + 1 || typeof app.running !== 'boolean' || !Number.isInteger(app.windows) || app.windows! < 0 || app.windows! > 32) throw new Error('Invalid application state receipt')
    if (app.capture_at === null ? app.capture_sha256 !== null || app.jpeg !== null : !time(app.capture_at) || app.capture_at > snapshot.snapshot_at + 1 || typeof app.capture_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(app.capture_sha256) || typeof app.jpeg !== 'string' || app.jpeg.length > 1398104) throw new Error('Invalid application capture receipt')
  }
  return snapshot
}

export function applicationFrame(app: PrivateApplicationObservation, snapshot: PrivateApplicationSnapshot, now = Date.now() / 1000): string | null {
  if (!snapshot.mission_active || app.capture_at === null || app.jpeg === null || now - app.capture_at >= 15 || now < app.capture_at - 1) return null
  if (app.jpeg.length % 4 || app.jpeg.length > 1398104 || !/^[A-Za-z0-9+/]+={0,2}$/.test(app.jpeg)) return null
  try {
    const data = atob(app.jpeg)
    if (data.length < 100 || data.length > 1048576 || data.charCodeAt(0) !== 255 || data.charCodeAt(1) !== 216 || data.charCodeAt(data.length - 2) !== 255 || data.charCodeAt(data.length - 1) !== 217) return null
  } catch { return null }
  return `data:image/jpeg;base64,${app.jpeg}`
}

export function applicationState(app: PrivateApplicationObservation, snapshot: PrivateApplicationSnapshot, now = Date.now() / 1000): string {
  if (!snapshot.mission_active) return 'Mission inactive; application state requires reconciliation'
  if (app.observed_at === null || now - app.observed_at > 5 || now < app.observed_at - 1) return 'Admission recorded; current application state unverified'
  return app.running ? `${app.windows} observed window(s)` : 'Application exited according to the last observation'
}
