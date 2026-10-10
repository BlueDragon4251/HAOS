import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProviderUsageSnapshot } from '../../../shared/missions.ts'
import { ProviderUsage } from './ProviderUsage.tsx'

function snapshot(): ProviderUsageSnapshot {
  return { snapshot_at: Date.now() / 1000, scope: 'broker', window_seconds: 86400,
    requests_day: 3, requests_minute: 1, requests_per_day: 200, requests_per_minute: 30,
    finished_requests_day: 2, unfinished_requests_day: 1, http_success_day: 1, http_error_day: 1,
    usage_reported_requests_day: 1, input_tokens_reported_day: 5, output_tokens_reported_day: 7,
    cost_available: false, monetary_cost: null }
}

describe('observed provider usage', () => {
  afterEach(() => vi.useRealTimers())

  it('keeps an unreachable broker distinct from a measured zero', () => {
    const unavailable = renderToStaticMarkup(createElement(ProviderUsage, { value: null }))
    expect(unavailable).toContain('Provider usage unavailable')
    expect(unavailable).not.toContain('requests in 24 hours')
  })

  it('labels partial subtotals and never presents HTTP completion as mission or dollar-cost proof', () => {
    const html = renderToStaticMarkup(createElement(ProviderUsage, { value: snapshot() }))
    expect(html).toContain('3/200 requests in 24 hours')
    expect(html).toContain('1/3 admitted requests')
    expect(html).toContain('Subtotals omit unavailable counters')
    expect(html).toContain('dollar cost are unavailable')
    expect(html).toContain('HTTP receipt does not verify a mission result')
  })

  it('distinguishes missing token metrics from actual reported zero tokens', () => {
    const html = renderToStaticMarkup(createElement(ProviderUsage, { value: { ...snapshot(), input_tokens_reported_day: 0, output_tokens_reported_day: null } }))
    expect(html).toContain('input 0')
    expect(html).toContain('output unavailable')
  })

  it('flags old receipts instead of presenting them as live counters', () => {
    vi.useFakeTimers().setSystemTime(new Date('2026-10-10T00:00:00Z'))
    const value = snapshot()
    vi.advanceTimersByTime(21000)
    const html = renderToStaticMarkup(createElement(ProviderUsage, { value }))
    expect(html).toContain('stale measurements')
    expect(html).not.toContain('3/200 requests in 24 hours')
  })
})
