import { describe, expect, it } from 'vitest'
import { applicationFrame, applicationSnapshot, applicationState } from './application-view.ts'
import type { PrivateApplicationSnapshot } from './missions.ts'

const mission = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
function snapshot(): PrivateApplicationSnapshot {
  return { mission, snapshot_at: 1000, mission_active: true, authority_available: true, applications: [{
    instance: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', program: 'approved-terminal', admitted_at: 900,
    observed_at: 999, running: true, windows: 1, capture_at: 999, capture_sha256: 'a'.repeat(64),
    jpeg: Buffer.concat([Buffer.from([255, 216]), Buffer.alloc(200), Buffer.from([255, 217])]).toString('base64')
  }] }
}

describe('actual private application observation boundary', () => {
  it('permits only the selected mission and unique bounded opaque instances', () => {
    const value = snapshot()
    expect(applicationSnapshot(value, mission)).toBe(value)
    expect(() => applicationSnapshot(value, 'cccccccc-cccc-cccc-cccc-cccccccccccc')).toThrow()
    expect(() => applicationSnapshot({ ...value, applications: [value.applications[0], value.applications[0]] }, mission)).toThrow()
  })
  it.each([{ program: '../owner' }, { instance: 'host-window-12' }, { windows: 33 }, { jpeg: 'x'.repeat(1398105) }, { observed_at: Infinity }, { capture_sha256: 'forged' }, { owner_credential: 'untrusted' }])('denies forged or unbounded frame metadata %j', delta => {
    const value = snapshot()
    expect(() => applicationSnapshot({ ...value, applications: [{ ...value.applications[0], ...delta }] }, mission)).toThrow()
  })
  it('expires images and blocks inactive/future frames rather than showing them as live', () => {
    const value = snapshot(), app = value.applications[0]
    expect(applicationFrame(app, value, 1000)).toMatch(/^data:image\/jpeg;base64,/)
    expect(applicationFrame(app, value, 1015)).toBeNull()
    expect(applicationFrame(app, { ...value, mission_active: false }, 1000)).toBeNull()
    expect(applicationFrame(app, value, 990)).toBeNull()
  })
  it('rejects non-JPEG, malformed base64 and injected URLs', () => {
    const value = snapshot(), app = value.applications[0]
    for (const jpeg of ['https://example.invalid/private.jpg', 'data:image/svg+xml,<svg>', 'A'.repeat(200), 'bad==data']) expect(applicationFrame({ ...app, jpeg }, value, 1000)).toBeNull()
  })
  it('requires a fresh real process receipt before displaying observed windows', () => {
    const value = snapshot(), app = value.applications[0]
    expect(applicationState(app, value, 1000)).toContain('1 observed window')
    expect(applicationState(app, value, 1010)).toContain('unverified')
    expect(applicationState({ ...app, running: false }, value, 1000)).toContain('exited according to')
    expect(applicationState(app, { ...value, mission_active: false }, 1000)).toContain('reconciliation')
  })
})
