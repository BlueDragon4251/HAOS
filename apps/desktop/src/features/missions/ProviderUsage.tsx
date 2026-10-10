import type { ProviderUsageSnapshot } from '../../../shared/missions.ts'

export function ProviderUsage({ value }: { value: ProviderUsageSnapshot | null }) {
  if (!value) return <p className="text-xs text-fg-4">Provider usage unavailable; the configured broker must be connected.</p>
  const stale = Date.now() / 1000 - value.snapshot_at > 20 || Date.now() / 1000 < value.snapshot_at
  return (
    <details className="rounded-lg border border-line p-3 text-xs text-fg-3">
      <summary>Provider usage{stale ? ' · stale measurements' : ` · ${value.requests_day}/${value.requests_per_day} requests in 24 hours`}</summary>
      <div className="mt-3 flex flex-col gap-2">
        <p>{value.requests_minute}/{value.requests_per_minute} requests in the last minute · {value.unfinished_requests_day} without a completion receipt</p>
        <p>Reported token subtotals: input {value.input_tokens_reported_day ?? 'unavailable'} · output {value.output_tokens_reported_day ?? 'unavailable'}</p>
        <p>Complete token metrics: {value.usage_reported_requests_day}/{value.requests_day} admitted requests. Subtotals omit unavailable counters.</p>
        <p>Broker totals include previous provider configurations. Per-mission attribution and dollar cost are unavailable. An HTTP receipt does not verify a mission result.</p>
      </div>
    </details>
  )
}
