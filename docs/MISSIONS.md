# Durable missions

Native managed-mode admission uses the independent controller. Retry preserves the request key until goal text changes; SQLite uniquely constrains actor/key. Failed HAOS admission never falls back to ordinary chat.

States: queued/running/waiting/blocked/failed/completed/cancelled. Actual transitions and upstream epoch/sequence receipts are persisted. One mission holds the shared agent-home lock. Pre-dispatch failures retry with bounded backoff/deadline. Session and dispatch markers are committed before prompt submission.

After dispatch, crash/disconnect/interruption is ambiguous: block and retain the lock rather than replay destructive work. Queued cancellation is immediate; running cancellation requests upstream interruption and waits for a receipt. Only root recovery after stopping execution can reconcile uncertainty.

Completed currently means a complete nonempty upstream turn without error/partial output, not independent verification of the user's objective. The UI displays that limitation.

Fixed local methods: health and missions.list/create/get/events/cancel/answer. Approval is only once/deny; owner/sudo/vault/unknown requests are refused. Gateway/voice/ordinary chat queue integration, parallel worktrees, outcome evaluators and protected journal retention remain incomplete.
