# Durable missions

Native managed-mode admission uses the independent controller. Retry preserves the request key until goal text changes; SQLite uniquely constrains actor/key. Failed HAOS admission never falls back to ordinary chat.

States: queued/running/waiting/blocked/failed/completed/cancelled. Actual transitions and upstream epoch/sequence receipts are persisted. One mission holds the shared agent-home lock. Pre-dispatch failures retry with bounded backoff/deadline. Session and dispatch markers are committed before prompt submission.

After dispatch, crash/disconnect/interruption is ambiguous: block and retain the lock rather than replay destructive work. Queued cancellation is immediate; running cancellation requests upstream interruption and waits for a receipt. Only root recovery after stopping execution can reconcile uncertainty.

`missions.pause` holds queued work **before prompt dispatch**. Its stored state is
`blocked` with phase `paused-before-dispatch`, so previous controllers also skip
it without a database downgrade. Herald labels this combination `paused`.
It holds no execution lock and survives SQLite/controller restart. Repeating pause
is harmless. `missions.resume` only returns this exact combination to the queue;
it preserves the absolute deadline, retry count and backoff. An expired paused
mission fails instead of executing. Queued/paused work can be cancelled immediately.
Neither API pauses or resumes running, waiting, completed or uncertain execution,
releases its locks, submits a prompt or repeats an external side effect. Safe
resumption of already dispatched long jobs remains an open requirement.

Completed currently means a complete nonempty upstream turn without error/partial output, not independent verification of the user's objective. The UI displays that limitation.

Fixed local methods: health and missions.list/create/lookup/get/events/cancel/pause/resume/answer. Approval is only once/deny; owner/sudo/vault/unknown requests are refused. The local trusted UI uses Unix peer identity; paired gateways additionally require explicit action capabilities and an owned mission. Gateway attachments, full voice playback, parallel worktrees, outcome evaluators and protected journal retention remain incomplete.
