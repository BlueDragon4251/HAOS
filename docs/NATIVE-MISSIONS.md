# Native conversation and durable missions

In installed HAOS, Electron identifies the managed runtime and Herald opens the
Hermes workspace at startup. Text messages, including existing transcribed-voice
callers, enter the controller's persistent `missions.create` API rather than
creating a parallel upstream chat turn. Slash text is also a mission goal; it
cannot execute upstream authentication or model-switch commands. An unavailable
mode-identification API fails closed. Standalone Herald keeps its existing chat
behavior when Electron explicitly identifies that mode.

The Hermes workspace shows actual controller missions, results, questions and
expandable recorded events. The model/backend process remains independent of
the window. This does not implement graphical application control, screenshots,
remote streaming or complete voice-response playback.

Queued work offers Pause; a persisted pause before dispatch offers Resume and
Stop. The UI uses the actual controller methods, displays its returned state and
recorded `mission.paused`/`mission.resumed` events, and never restarts the model
itself. The original deadline continues while paused. Uncertain blocked work
keeps its separate owner-reconciliation message and offers no Resume. If a worker
claims the mission before a Pause request arrives, the controller refuses the
request. The HAOS `mission.pause` command now pauses the durable queue rather than
cancelling an execution. Standalone Herald retains its existing interruption path.

Before admission, the renderer saves only a random request UUID, SHA-256 goal
digest and timestamp. It stores no plaintext message in these receipt records.
The digest is metadata, not encryption: someone with browser-storage access can
guess a predictable message and compare its hash. Submitted goals remain subject
to the controller's documented privacy limits.

After a lost response or window reload, `missions.lookup` checks the saved key
under the actual Unix peer's identity. Reload never resends a prompt. Re-entering
the exact original text explicitly retries with the same key; the SQLite actor/key
constraint returns the original mission. Unknown admissions remain visible.
Malformed storage, changed content, too many unresolved intents or mismatched
controller receipts prevent admission/receipt removal. No non-idempotent action
is replayed by this recovery mechanism.

Tests cover lost replies, reload lookups, unresolved receipts, changed goals,
storage failure, corrupt metadata, mismatched receipts, managed text/voice/slash
routing and explicit standalone behavior. A separate real Unix-socket probe
checks durable idempotency and rejects a caller-supplied actor during lookup.
These local tests do not prove an external provider/model turn. The legacy
authenticated backend protocol still exists; a comprehensive review of every
backend capability and UI entry point remains a release requirement.
