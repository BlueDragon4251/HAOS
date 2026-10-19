import { describe, expect, it } from 'vitest'
import { observerRpcAllowed } from './haos-observer-rpc.ts'

describe('HAOS observer WebSocket compatibility gate', () => {
  it.each(['gateway.ping', 'session.list', 'session.active_list',
    'session.events.since', 'session.events.stats'])('permits approved read-only RPC %s', method => {
    expect(observerRpcAllowed(true, method)).toBe(true)
  })

  it.each(['config.get', 'config.set', 'model.options', 'session.create',
    'prompt.submit', 'session.interrupt', 'slash.exec', 'session.delete',
    'model.save_key', 'unknown.command'])('blocks legacy command %s before dispatch', method => {
    expect(observerRpcAllowed(true, method)).toBe(false)
  })

  it('does not interfere with classic Herald mode', () => {
    expect(observerRpcAllowed(false, 'config.get')).toBe(true)
    expect(observerRpcAllowed(false, 'prompt.submit')).toBe(true)
  })
})
