# Native dashboard authority

The HAOS image installs `haos.web_access.DashboardAccess` on the actual pinned
Hermes FastAPI app before the canonical `hermes serve` CLI starts it. Upstream
source files remain unchanged. Authorization happens at the HTTP/WebSocket
server, independently of Electron, model output and message text.

The observer reads `/etc/haos/ui-token` (root/haos-ui, 0640). The full backend
credential is `/etc/haos/backend-token` (root/root, 0600), delivered only to the
controller and isolated backend through systemd credentials. Native attach
requires the version-2 descriptor and the UI token path; a version-1 descriptor
or private-token fallback is rejected. The agent does not receive the native
host-command bridge or owner/provider keys.

| Observer surface | Permitted behavior |
| --- | --- |
| HTTP | GET health, own backend identity/status/system stats, session list/search/stats and bounded session messages/timeline |
| `/api/ws` | `gateway.ping`, `session.list`, `session.active_list`, `session.events.since`, `session.events.stats` |
| Mission changes and tool answers | Existing persistent HAOS controller, authenticated by Unix peer identity |
| Provider/credential/system setup | Existing password-authenticated owner CLI/recovery console |

Everything else defaults to denial, including raw prompt/session mutations,
configuration/environment/OAuth, PTY/console, arbitrary files, browser-controller
registration and server-request answers over the observer's upstream connection.
The separate controller capability retains the existing real session, turn,
cancellation and question protocol. Public health retains its content-free
liveness response. Loopback peer/path checks run before translation; ambiguous
headers/query tokens, encoded paths, duplicate JSON keys, RPC batches, binary and
oversized input are rejected. Only an allowed observer scope is translated to
the upstream credential. Cookies/tickets are stripped from that scope.

Observer HTTP output is bounded to 4 MiB, buffered before publication and served
without compression/cache cookies. Known backend/UI/model capabilities are
redacted even across response chunks. WebSocket JSON text uses the same known
capability redaction; it cannot carry binary output. This does not prove general
secret detection, journal/session encryption or complete mission privacy.

`haos-dashboard-policy.service` runs before both execution services and greetd.
Initialization and the boot migration require root-owned, non-writable, regular,
single-link files and a trusted directory. Migration **replaces** the old full
observer-readable backend token; mode changes alone would leave copied tokens
usable. The descriptor is published last, and a partial migration repeats safely
before services start. A healthy version-2 pair remains stable across boots;
an exposed version-2 backend credential is rotated. Unknown descriptors and
symlinks/hardlinks/foreign ownership fail closed. Migration refuses live execution
services. Updating an older installed image requires a reboot into the new image;
the native shell cannot reuse the old descriptor during migration.

Local verification includes 27 authorization/parsing/privacy contracts, six real
root/UID credential migration probes in a network-disabled disposable container,
and a separate **actual pinned Hermes** HTTP/WebSocket process. That process
proves authenticated observer reads, denied configuration/credential/terminal
routes and direct turns, preserved private-controller session creation and no
fixture capabilities in its process log. No provider is called and no successful
model turn is claimed. The image build requires this same real probe and saves
`ui-access-build-probe.json`; both installed guest boots additionally require
actual observer private-file denial and authenticated read/protected-route tests.
Matching image/installed results are still required for this new boundary.

Graphical owner provisioning, owner locking, a complete GUI capability broker,
plugin capability enforcement, per-mission privacy/device authorization and real
credentialed provider/gateway acceptance remain open. Legacy settings requiring
owner/configuration rights currently report denial in HAOS and need a native
authenticated owner flow. The standalone Herald deployment keeps its existing
backend attach behavior.
