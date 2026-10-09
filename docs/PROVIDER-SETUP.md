# Credential-isolated HAOS providers

The installed owner CLI provisions OpenAI Codex OAuth, OpenAI API, OpenRouter API,
or an explicitly configured loopback OpenAI-compatible local model. These are
the interfaces supported by the pinned Hermes runtime; no provider response is
fabricated when credentials are absent.

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
