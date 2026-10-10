# Read-only system health and resource admission

The independent mission controller samples actual Linux `/proc` memory/CPU
counters, filesystem free space, available hwmon critical thresholds and GPU busy
counters. It queries only fixed HAOS/greetd units using read-only `systemctl show`
properties; it exposes no journal, process command line, environment, personal
file content, arbitrary service selector or repair endpoint.

Herald's native Hermes/Missions workspace displays these timestamped measurements,
including actual service cgroup memory/task counters. Unknown hardware and first
CPU-delta samples remain absent. Service counters cover the entire service and
are not represented as per-mission measurements or model costs.

Sampling runs independently of the desktop and model turn, every five seconds.
Dispatch requires fresh storage/memory measurements. Less than 256 MiB filesystem
free space, less than 64 MiB available RAM, or an exposed sensor's actual critical
temperature pauses new claims. Jobs remain in the persistent queue, unclaimed and
without additional attempts. Admission resumes after a fresh safe sample. Errors
in required storage/memory measurements also prevent dispatch; UI health failures
never select an alternate execution path. CPU/service measurement errors are
reported without inventing values. A service failure is visible as degraded health.

Already running/uncertain jobs retain their existing deadline, interruption and
reconciliation rules. The sampler never blindly retries external actions or kills
an action while reporting its outcome as successful. Logs contain only changed
health classifications and fixed metadata labels; no exception text or journal
extract enters the mission API.

Tests use actual kernel/filesystem measurements and separately exercise pressure,
unknown sources, stale snapshots, fixed read-only service selection and once-only
resumption of a cancelled scheduler fixture. These are not live model-turn tests.
Automatic repair, independent boot/theme/update watchdogs, full hardware diagnosis,
exact per-mission resource/cost limits, authenticated critical notifications and
installed UI/hardware acceptance remain open.
