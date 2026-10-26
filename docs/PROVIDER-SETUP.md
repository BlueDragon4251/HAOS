# Credential-isolated HAOS providers

HAOS reads a generated, commit-pinned snapshot of Hermes's own provider registry.
The snapshot contains 39 regular entries and 14 additional bundled profiles.
The HTTP broker implements Chat Completions, Responses and native Anthropic
Messages, with exact owner-selected endpoints and local function-tool admission.
Account flows run upstream login/refresh under the separate provider identity.
Native SDK, Gemini, Copilot/ACP, MoA, model discovery and wire-contract progress
and remaining acceptance are tracked in [PROVIDER-PARITY.md](PROVIDER-PARITY.md).

`haos-provider` is a separate unprivileged identity. Real API keys stay in
root-private `/etc/haos/provider-credentials`, delivered by systemd credentials.
Codex access/refresh tokens stay in the provider's private
`/var/lib/haos-provider/.hermes` state, using Hermes's unmodified device-code
login, credential pool, resolver and refresh. Neither state is mounted into
the model/terminal namespace or gateway process.

The agent receives a **scoped local capability**, not the provider key, and an
immutable named-custom-provider configuration. The broker accepts only the
owner's listed models and selected Responses/Chat Completions route. It refuses
remote MCP/computer/file tools, remote continuation state and background jobs;
Hermes's local function tools retain the existing agent/policy boundary.

Remote endpoints are fixed verified HTTPS URLs. No redirect, caller URL,
cookie, authentication header or arbitrary header is forwarded. The root-bound
systemd activation socket listens only on `127.0.0.1:9120`. The socket-UID guard
permits that port only when protected provider policy is configured. Changing
or disabling it requires all execution services and the broker/socket stopped;
connections die, capability rotates, and nftables is reinstalled. Configuration
withdraws the old authority descriptor durably before replacing credentials,
so an interrupted switch cannot send a new provider's key to the old route.

## Owner flows

Complete onboarding and retain recovery codes before enabling autonomous work.
Authenticate as the separate owner. Secrets are entered only at the trusted
local console; never pass keys/tokens as arguments, chat messages or Git files.

```sh
sudo haos-owner stop
sudo haos-owner provider login-codex
sudo haos-owner provider configure openai-codex --model gpt-5.4
sudo haos-owner start
```

`login-codex` runs the real pinned Hermes OAuth flow in a separate hardened
transient service with an owner PTY. Follow the displayed OpenAI device-code
instructions and account authorization. Nothing here proves your subscription
supports a particular model; select one your account actually supports.
`configure` verifies the private OAuth store with the real read-only resolver
before publishing policy. It does not run or claim a model turn.

API alternatives prompt without echo for the key:

```sh
sudo haos-owner stop
sudo haos-owner provider configure openai --model gpt-5.4
# Or: configure openrouter --model YOUR_SUPPORTED_MODEL
sudo haos-owner start
```

For an owner-installed compatible local server:

```sh
sudo haos-owner stop
sudo haos-owner provider configure local --endpoint http://127.0.0.1:11434/v1 --model YOUR_LOCAL_MODEL
sudo haos-owner start
```

This provisions routing; it does not install a local server or claim available
models. Local endpoints require a literal loopback address and an explicit
nonprivileged port, excluding the Hermes/backend broker ports.

`--allow-model` can be repeated for an explicit allowlist. `--api-mode` selects
the supported protocol; Codex OAuth always requires Responses. Per-minute and
per-day request caps default to 30/200. Admission commits before dispatch, so
restart or uncertain dispatch does not erase consumed quota. There are two
concurrent calls, bounded request/response/frame sizes and stream deadlines.
Provider 401/403/429/5xx status reaches Hermes without leaking provider bodies.
Incomplete streams never receive a fabricated successful terminal response.

Bedrock accepts private JSON containing either `access_key_id` and
`secret_access_key` (optional `session_token`), `profile`, or `bearer_token`.
An empty field selects the private provider service's normal AWS SDK identity.
Automatic protocol selection uses native Claude Messages, reviewed Mantle GPT
Responses, and Converse for other models including GPT-OSS. Mantle's hostname
is derived from the approved Bedrock runtime region. Control-plane discovery
does not enumerate Mantle-only models; use a supported model ID explicitly.
Discovery and protocol setup do not prove account access.

```sh
sudo haos-owner provider status
sudo haos-owner stop
sudo haos-owner provider disable
sudo haos-owner provider logout-codex
```

Disabling removes local routing and API credentials. Codex logout removes the
local OAuth grant through upstream; revoke account sessions at OpenAI if remote
revocation is needed. The previous agent configuration and mission database
are not deleted. The mounted model configuration is owner-managed; ordinary
upstream UI configuration writes cannot grant another model or credential.

## Privacy and evidence

The broker logs only generated request ID/status. Its private usage database
stores time/provider/model/status and actual token counts when available, with
30-day metadata retention. It stores no prompt, response, API key or screenshot.
Structured output/SSE frames redact known credentials before delivery, including
values split across transport writes. Mission usage events still come from
Hermes. Request limits are not a verified monetary budget; dollar pricing and
per-mission cost limits remain open.

The fixed authenticated `GET /v1/haos/usage` route exposes only rolling
24-hour/minute aggregates and current request limits from this durable broker
ledger. It includes unfinished requests, HTTP status counts, token **subtotals**
actually reported, and coverage of complete token receipts. Missing tokens stay
null; actual reported zero stays zero. These totals include previous provider
configurations and have no per-mission attribution. `cost_available=false` and
`monetary_cost=null` explicitly avoid a dollar-price claim.

The controller samples this bounded literal-loopback route with its existing
scoped capability and sends fixed validated fields to Herald's Hermes workspace.
UI/backend restart does not reset usage. Broker outages clear the current receipt
rather than fabricating zero; the UI labels absent/stale observations. Reads
cannot request history/configuration, carry bodies, refresh OAuth credentials,
call a model or consume a model admission. Duplicate/missing capabilities,
query variants, arbitrary fields, inconsistent counts and monetary claims fail.
Local SQLite and real loopback HTTP probes verify this independent aggregate
path; they do not prove a real provider/model turn or actual billable usage.

Unit/local HTTP tests include hostile credential reflection and refused routes.
Root probes verify actual private modes, UID denial, capability rotation and
interrupted switches. The runtime build verifies the actual pinned Hermes
resolver, named provider, Responses function payload and OAuth helper contract
without network/model calls. Local fixture responses are not model evidence.

Required external acceptance: owner authorizes the actual Codex OAuth device
flow (or enters a valid API key), selects an available model and supplies a
real Telegram bot token with an exact allowed sender/chat binding. Run a real
durable mission with a tool call and usage/error receipts, then a real Telegram
mission/reply. No such credentials were supplied in this cloud session.

Installed socket activation, first-boot credential delivery and matching new
ISO integration still require exact-source VM evidence. General encryption at
rest, every upstream log/vault path, full exfiltration controls, GUI provisioning,
additional providers and monetary budgets remain separate open requirements.

## systemd credential ACL compatibility

The loader validates effective POSIX ACL rights as well as owner/type/size. A
systemd root-owned 0400 credential with a named read ACL for the current service
UID has a visible 0440 mask; its owning group still has no access. This precise
case is accepted. Ordinary group-readable files, named foreign users/groups,
service write grants, world access, symlinks, hardlinks and oversized credentials
remain rejected. Actual root/dropped-UID fixtures exercise each case; the real
production-hardening systemd probe reads its delivered credential through this
same loader. Corrected Fedora image acceptance remains required after the
concrete controller-startup failure in `e954dd3` / `720c08c` guest evidence.

## Several configured providers

Configuring another provider preserves existing routes and credentials. Legacy
single-provider policy is migrated atomically to version 2; every change still
requires stopped execution, rotates the scoped broker capability, and publishes
the authority descriptor last. Existing missions, data and accounts are retained.

```sh
sudo haos-owner stop
sudo haos-owner provider configure anthropic --model YOUR_CLAUDE_MODEL
sudo haos-owner provider configure deepseek --model YOUR_DEEPSEEK_MODEL
sudo haos-owner provider set-default anthropic
sudo haos-owner provider fallbacks deepseek --fallback openrouter
sudo haos-owner provider remove deepseek
sudo haos-owner start
```

Only configured routes with the same native wire protocol can be fallbacks.
Explicit fallback selection authorizes sending a prompt to those providers.
Fallback runs on an upstream HTTP 429/502/503/504 before output starts. A lost
connection or a partial stream is ambiguous and is never automatically replayed.

In graphical provider management, a model team (MoA) combines one or two
reference models with an aggregator. First configure its providers/models, then
reload the saved provider selection and choose approved models from the team
pickers. The optional second reference is initially off. Every selected provider
receives the prompt; activating the team explicitly selects those providers.
The aggregator combines their responses. No preset JSON or credential re-entry
is needed. Choosing a normal route as default returns to that single provider.
Each attempt is durably charged to the broker request quota before dispatch.
`GET /v1/models` returns the owner-approved model list, not a live discovery claim.

Generic account commands are `provider login PROVIDER`, `provider auth-status
PROVIDER`, and `provider logout PROVIDER`. The graphical physical setup launches
the same private provider-UID OAuth process in a dedicated native terminal;
credentials are neither sent to the model nor written to the system journal.
Qwen's login now starts a fresh device-code authorization with PKCE in the
private provider terminal. Open only the displayed checked `chat.qwen.ai`
authorization URI and approve its user code; Ctrl-C cancels. No Qwen CLI or
pre-existing token file is required. The access/refresh tokens and device code
are never displayed. Pending/slow-down, expiry, denial and invalid responses
are handled with bounded polling; failed/cancelled login retains old credentials.
Successful credentials use Hermes's private Qwen storage and native refresh.
The graphical account-status control checks the private credential helper
without stopping missions or claiming model inference. Account login is not
proof of account entitlement or a successful inference.

OpenRouter account login always uses the pinned PKCE code-entry path in the
protected owner terminal. Open its displayed authorization URL on your browser,
approve it and paste the authorization code into the masked terminal prompt.
No browser callback listener is needed. The returned API key stays in the
private native credential pool; status checks that pool and local logout
clears it. OpenRouter returns an API key rather than a refresh token. Revoke
the key in OpenRouter's account controls to invalidate it remotely.

Anthropic subscription login retains Hermes's native PKCE flow. Open its
displayed Claude authorization link, then paste the complete `code#state` into
the protected terminal. Code entry is hidden; terminal echo is restored after
success, denial or cancellation. A private terminal is required. Tokens stay
in the native provider credential pool, with native expiry refresh. Local
logout does not certify remote revocation or subscription/model entitlement.

MiniMax accounts have separate global and China endpoints. Select
`https://api.minimax.io/anthropic` or `https://api.minimaxi.com/anthropic`
in the graphical provider form before account login/status. The protected
helper receives only the corresponding fixed region, and configuration refuses
an account authenticated for the other endpoint. CLI users select China with
`sudo haos-owner provider login minimax-oauth --region cn` and check it with
`sudo haos-owner provider auth-status minimax-oauth --region cn`; the default
region is global. Configure the route with the matching `--endpoint`. Logout
removes local account state; revoke the grant with the provider for remote
revocation. Login does not prove model or subscription access.

Account status is available without stopping missions, from the same protected
owner console. MiniMax status performs no token refresh: an expired access token
with stored refresh credentials is marked pending until the next approved model
request refreshes it. Region checks precede that refresh. A stored credential
does not prove that the provider will still accept it.

For cloud credential JSON, the graphical provider page also offers a private
file picker. Select a regular JSON file belonging to the enrolled owner or root,
with private permissions (for example mode 0600), no extra hard links and at
most 16 KiB. AWS accepts its supported IAM/profile/bearer object, Google accepts
its service-account or authorized-user document, and Azure accepts the service
principal object described above. API keys can still be entered directly.
The importer validates data and leaves the file unchanged. Imported content is
masked and is published privately only when configuring the selected provider.
Changing providers discards it, including an import still completing in the
background. Empty-file import does not silently choose the SDK identity; leave
the cloud field blank only when you intend to use that separately prepared identity.

Vertex's **Modellliste laden** reads the Model Garden publisher catalogue using
the private Google identity and configured regional endpoint. With an empty
model field it selects Google; enter a publisher prefix such as `meta/...` before
loading to request that publisher. Selecting a catalogue ID does not prove
project access or OpenAI-endpoint compatibility. The GUI marks this distinction;
publication still requires explicit provider/model configuration. Changed input
discards an in-flight result. API errors retain clearly identified offline
suggestions rather than claiming a successful catalogue or inference.

AWS SDK identity resolution stays inside the private provider service. A named
profile or standard service identity is refreshed by the actual SDK; every
request uses one frozen identity for signing and response redaction, including
temporary role session tokens. Profile/default-chain selection requires that
identity to be provisioned for the provider service itself. It does not read
the desktop owner's AWS files, automatically provision SSO, or prove access to
a selected model. Removing the HAOS route withdraws local authority; remote
IAM/SSO revocation remains an account-side operation.


Gateway setup now includes ntfy with a real private service profile and explicit
all-publishers topic approval. Use the owner gateway page or protected CLI
prompts; no token belongs in a command argument or an agent session. See
[ntfy owner setup and service integration](HERMES-RUNTIME.md#ntfy-owner-setup-and-service-integration-2026-10-25)
for the server ACL requirement, identity limits, tested paths and remaining
media/live/installed acceptance.

### Home Assistant gateway: exact entity events and shared replies

In graphical owner management select `homeassistant`, save the instance's HTTPS
URL (with a system-trusted certificate) and a privately entered long-lived access
token. HAOS opens the authenticated outbound WebSocket; no public HAOS webhook
is required. Save configuration before pairing. Pair the actual 32-character
Home Assistant user ID with one exact entity such as `sensor.room`, then choose
mission creation and, optionally, reply reading. Scope and thread do not apply.

Replies are persistent notifications visible to **all users of the instance**.
The initially unchecked shared-notification approval must be selected to grant
reading. For system/automation events select the separate initially unchecked
system trust option: the sender becomes `system` and the grant covers every
system producer of that precise entity. Do not use this option to identify an
individual human. Unknown human senders remain unauthorized.

CLI equivalents are `haos-owner gateway setup home homeassistant` (private token prompt), followed by `haos-owner gateway pair`
with the exact sender/entity, `--homeassistant-shared-notifications` for reading,
and `--homeassistant-trust-system` only for a `system` sender. Consult `pair
--help` for the existing binding and identity arguments. `haos-owner gateway
retry-homeassistant-auth home --note 'account corrected'` requests
an audited offline recheck after correcting account access. It does not bypass
server authentication, pending rate limits, revocation or uncertain delivery.

Inspect the displayed gap timestamp after disconnects. The stock remote history
API cannot prove original event authorship during an outage, so successful
reconnection does not close that gap. This path does not enable Home Assistant
device-control tools, media/voice or private per-recipient notifications.

### IRC text gateway

The owner gateway page supports one isolated IRC connector. Save the TLS
hostname, port (normally 6697), bot nickname and one exact canonical channel
(`#channel` or `&channel`). Certificates must validate against the system trust
store. Enter the private SASL account/password and optional server PASS password;
connecting without SASL instead requires a separate, initially unchecked owner
approval. Password fields clear after submission and when changing the endpoint,
connector or platform. Saved configuration metadata contains no private passwords.

Pair each permitted sender by its exact **authenticated IRC account**, preserving
case, rather than nickname or hostmask. The saved TLS server/port and channel
bind the grant; an unsaved endpoint cannot be approved from the pairing form.
Messages must address the bot. Unknown accounts remain unauthorized. Replies
are visible to channel members: approve `read` only when that audience is intended.
The native pinned Hermes adapter runs behind HAOS account, policy, lease,
credential, replay and delivery boundaries; arbitrary plugins gain no authority.

CLI: `haos-owner gateway setup irc-main irc` uses private password prompts.
Use `haos-owner gateway pair --help` for binding, connector, account, channel,
identity and permission arguments. The matching saved server scope is derived
when omitted. `haos-owner gateway retry-irc-auth irc-main --note 'account corrected'`
records an offline owner decision after fixing authentication; it preserves rate
limits, revocation, retained inputs and outage gaps. Restart the gateway service
explicitly after setup/recovery. An unpaired connector does not connect.

The server must support account-tag, server-time, message-tags and stable message
IDs. Sending additionally requires echo-message, labeled-response and batch.
Server echoes are correlated with each native message chunk and journaled before
HAOS accepts completion. An echo may be synthetic under IRCv3 rules, so it **does
not prove that channel members received the message**. Uncertain or interrupted
writes are not automatically resent; use the existing audited delivery recovery
controls. Unobserved events during disconnection cannot be reliably recovered
from stock history. NickServ shortcuts, DCC, media and voice are not enabled.
This is software/loopback contract validation, not external IRC account acceptance.
