import type { MissionServiceHealth } from '../../../shared/missions.ts'

function bytes(value: number): string {
  return `${(value / 1024 ** 3).toFixed(1)} GiB`
}

export function SystemHealth({ value }: { value: MissionServiceHealth['system'] }) {
  if (!value) return <p className="text-xs text-fg-4">System measurements pending.</p>
  const stale = Date.now() / 1000 - value.at > 20 || Date.now() / 1000 < value.at
  return (
    <details className="rounded-lg border border-line p-3 text-xs">
      <summary className={value.status === 'critical' || stale ? 'text-danger' : 'text-fg-3'}>
        System health: {stale ? 'stale measurements' : value.status}
        {value.cpu_busy_percent != null && ` · CPU ${value.cpu_busy_percent}%`}
        {value.memory && ` · RAM ${bytes(value.memory.total - value.memory.available)} / ${bytes(value.memory.total)}`}
        {!value.can_dispatch && ' · New missions paused for resource safety'}
      </summary>
      <div className="mt-3 flex flex-col gap-2 text-fg-3">
        <p>Measured {new Date(value.at * 1000).toLocaleTimeString()}. Service counters include all work in that service.</p>
        {Object.entries(value.disks ?? {}).map(([name, disk]) => <p key={name}>{name}: {bytes(disk.free)} free of {bytes(disk.total)}</p>)}
        {value.temperatures?.map(row => <p key={row.sensor}>{row.sensor}: {row.celsius} °C{row.critical_celsius != null ? ` · critical ${row.critical_celsius} °C` : ''}</p>)}
        {value.gpus?.map(row => <p key={row.device}>{row.device}: {row.busy_percent}% busy</p>)}
        {value.services?.map(row => <p key={row.unit}>{row.unit}: {row.active} / {row.state}{row.memory_bytes != null ? ` · ${bytes(row.memory_bytes)}` : ''}{row.tasks != null ? ` · ${row.tasks} tasks` : ''}</p>)}
        {value.alerts.length > 0 && <p role="alert" className="text-danger">{value.alerts.join(', ')}</p>}
        {value.errors.length > 0 && <p>Unavailable measurements: {value.errors.join(', ')}</p>}
      </div>
    </details>
  )
}
