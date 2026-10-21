# Hermes parity work — development, not release acceptance

## Private cloud credential-file import (2026-10-21)

The native owner GUI now imports AWS, Google and Azure credential JSON from an
explicitly selected private file. The root/physical-seat helper opens a regular
file without following a symlink, requires owner/root ownership, no group/world
rights, one link and at most 16 KiB, then applies the existing provider-specific
data validator. No provider SDK runs in the root GUI and no source file changes.
The content enters only the existing masked input, is cleared on configuration/
provider change, and is discarded if provider selection changes while background
reading completes. Import alone performs neither publication nor inference.

Eleven ordinary-user data-file cases pass, including actual mode/link/size
checks, fixed Google token endpoint and refusal of non-cloud/non-seat choices.
Both runtime variants pass **839 tests, two existing skips**. Actual Tk workflow
scripts pass at both display sizes, checking masked import and stale-selection
discard. A new real-root CI case checks actual ownership/mode/seat denial; it is
not counted as a local root pass. All five gates at predecessor `296ae00` passed,
including both native provider runs with the MoA finalization regression.
Live credentials, installed graphical onboarding and artifacts remain unaccepted.

## MoA admission handoff under cleanup delay (2026-10-21)

Push workflow `39574281627` at `ad1f2c4` exposed a genuine broker handoff race:
the aggregator can arrive after receiving two complete reference bodies but
before their handlers finish local finalization and release the two-call cap.
It then received HTTP 429. The parallel PR run passed, so its success alone did
not establish reliability. The actual pinned-engine probe now delays the first
two finalizations deterministically; that probe reproduced 429 before the fix.

Broker admission now waits at most one second for an existing slot, retaining
the same two concurrent calls and dispatching no upstream request while it
waits. This performs no retry. The delayed actual MoA probe now passes all three
approved broker calls. A separate real-HTTP test holds two upstream calls open
and confirms a third request is bounded, gets 429 and never reaches a provider.
Both runtime variants pass **828 tests, two existing skips**; the 390-case HTTP
matrix still passes. Root/GUI/general CI passed on predecessor `ad1f2c4`,
including the new real-root legacy migration test; the handoff fix needs its
own CI receipt. No live inference or installed/release acceptance is claimed.

## Graphical MoA model selection (2026-10-21)

The owner now selects approved reference and aggregator models in native GUI
pickers instead of writing preset JSON. The complete owner-approved allowlist
is available, including models other than a route's default. A second reference
is optional and disabled by default; the interface states that every selected
provider receives the message. The saved provider selection can be refreshed
after configuring another provider. No team-activation button is offered before
there is an approved model. Picker widths remain bounded on small screens.

Creating the first team from legacy version-1 configuration now migrates that
route and its private credential atomically, retaining the GUI's `default`
identity. A new real-root authority case checks credential preservation,
capability rotation and that stale/unapproved model choices leave protected
files unchanged; it remains a required CI test, not a local root pass.

The exact workflow's actual interactive Tk scripts passed locally on Xvfb at
1280x800 and 640x480, including one/two-reference dispatch, a non-default model,
empty configuration and a long model ID. This uses an extracted Debian Xvfb
fixture as the ordinary user, with no installed owner/physical-seat claim.
Both runtime suites still pass **827 tests, two existing skips**; the real
pinned MoA engine also performs its three approved loopback broker calls.
GUI fixtures do not certify live models, installed boot or final artifacts.

## Read-only account status and regional refresh admission (2026-10-21)

MiniMax status now reads native private state without network access or token
rotation. Expired access with a stored refresh grant is reported as refresh
pending, not live account verification. The broker checks the stored region and
approved inference endpoint before asking the pinned resolver to refresh.
The actual native account probe verifies unchanged private JSON and zero HTTP
requests during status, and refuses the other region even when the token has
expired. The correct approved request then performs the actual native refresh.

Owner CLI account status now works while missions run, retaining the protected
console helper. Invalid regional account arguments fail before route withdrawal
or owner-file changes. Both local runtime variants pass **827 tests, two existing
skips**; the 22 native account cases and OpenRouter/Copilot/Anthropic account
probes pass again. No account entitlement or live inference is claimed.

## Complete chunk trailers (2026-10-21)

A further real stdlib regression at `88cea1e` reproduced acceptance of a zero
chunk followed by EOF before the trailer's final blank line. The bounded HTTP
response class now requires that delimiter and caps discarded trailers at
64 KiB, for inference and private model discovery. Valid empty/nonempty trailers
remain accepted; missing terminal chunks, partial chunks and partial trailers
fail. The SDK/HTTP matrix now passes **390** cases across the same 39 profiles,
including an incomplete-trailer case for every profile. Minimal and full suites
each pass **825 tests, two existing skips**. The 20 native AWS, 49 cloud-model
and six Messages SDK cases still pass. Earlier receipts retain their exact
inputs; new source hashes and fixture receipts are archived separately. Root
kernel/UID, live account, installed boot and release gates remain distinct.

## Native and chunked terminal-framing regressions (2026-10-21)

New real HTTP regressions reproduced two completion defects at `f1bff80`.
The native Gemini path forwarded a finish chunk before a short HTTP body failed;
the stdlib chunked SSE path could accept a missing terminal HTTP chunk because
`readline()` uses `peek()`, which suppresses an incomplete-read error. Checking
fixed length alone was insufficient. HAOS now checks the completed chunk state
and holds native Gemini/Bedrock finish events, including native Claude stop
deltas, until the SDK iterator and HTTP framing finish successfully. Early text
and tool deltas continue without waiting for completion; buffered frames retain
ordering and the existing output/deadline limits. Failed streams are not retried.

The required matrix now passes **351** actual builder/SDK/HTTP cases across all
39 HTTP profiles, adding valid chunked streams and missing-terminal-chunk cases
to the previous 273 cases. Native Gemini passes six HTTP cases, including short
JSON/terminal bodies. Native AWS now passes 20 cryptographically checked IAM/
Bearer Mantle/Claude cases, including absent terminal HTTP chunks. The six
Converse cases and eight ordered-replay HTTP calls still pass. Minimal and full
runtime suites each pass **822 tests, two existing skips**. Root-only gates remain
required in CI. All results are local fixtures, with source hashes archived in
`docs/evidence/2026-10-21`; no live inference or installed/release acceptance.

## Protected Anthropic native account login (2026-10-21)

Anthropic subscription login now runs the pinned native OAuth-add flow with
terminal echo disabled while its authorization-code prompt is active. It
requires a protected terminal and restores the original terminal state even
on failure. Seven actual HTTP/PTY cases check PKCE/state, hidden code entry,
terminal restoration, native private-pool persistence, automatic expiry refresh
through the actual broker, status and native logout. State mismatch, empty code,
denial, missing access token, malformed JSON and short HTTP bodies fail without
publishing a credential. The build and provider workflow require this probe.
These are local protocol/PTY fixtures, not a live Claude account, entitlement,
installed physical setup or inference acceptance.

## Fresh Copilot device authorization (2026-10-21)

The private account helper now validates a newly authorized Copilot token's
format and supported GitHub token family before saving it. A failed or invalid
reply retains the previous private owner account. Seven actual pinned
device-code HTTP cases verify success, pending, RFC 8628 slow-down timing,
denial, expiry, malformed device data and unsupported classic PAT replies.
The existing private redirect-safe transport is used; only fixture destinations
are replaced with loopback. Device/access secrets are not printed and the native
environment file remains private. Both build and provider CI require this probe.
Actual account entitlement, external authorization and installed UI acceptance
remain separate; the earlier exchange/cache fixtures still cover API-token use.

## Native Codex account HTTP contracts (2026-10-21)

Nine additional required build/CI cases execute the pinned Codex device-code
client, authorization-code/verifier exchange, rotating refresh, private native
storage, broker resolution, status and logout against real loopback HTTP.
Pending authorization, device rate limits, invalid device/exchange/token replies,
refresh denial and refresh rate limits are checked. The broker receives the
refreshed access token; the rotating refresh grant stays out of model headers.
Private files retain mode 0600 and tokens/verifiers are not printed. No real
OpenAI account, subscription, inference or remote revocation is tested.

## OpenRouter protected-terminal account flow (2026-10-21)

HAOS now explicitly uses the pinned PKCE headless/code-entry functions for
OpenRouter, which work from the isolated provider terminal without a browser
callback. The returned key uses the native OAuth-add credential-pool format.
The generic pinned status/logout dispatcher does not recognize OpenRouter's
pool: HAOS now checks that private pool and clears its account/legacy env state
through native storage functions. Root-side route withdrawal remains required
before local logout. Remote key revocation remains an owner account action.

Nine actual local HTTP cases check PKCE, private pool/status/broker/logout,
denial, rate limits, missing/invalid keys, malformed/truncated responses,
empty code and cancellation. Failed authorization preserves a pre-existing
owner credential. No authorization code, verifier or returned key is printed.
The probe is required by provider CI and image build; these fixtures do not
certify real OpenRouter authorization, inference or remote revocation.

## Native account flows and MiniMax region selection (2026-10-21)

The required build/CI probe now executes 22 actual pinned Nous, xAI and
global/China MiniMax device-login, refresh, private-storage, broker, status and
logout cases over loopback HTTP. It checks pending/denied authorization,
malformed device/token replies and MiniMax PKCE/state rejection. Failed login
publishes no pool credential; a fresh successful MiniMax login has exactly one
native singleton-seeded pool entry, avoiding duplicate rotating refresh grants.
Refreshed credentials reach only the approved broker endpoint; cross-region
MiniMax routing fails before any network dispatch. These are fixtures, not live
accounts or remote revocation evidence.

Graphical login/status now uses the selected MiniMax endpoint to choose the
fixed global/China region. CLI account actions accept `--region cn`; other
providers reject that regional flag. Endpoint validation and trusted-seat gates
run before execution, and status does not stop missions. Local minimal and
full-runtime suites each pass 818 tests with two existing skips; root-only
backup/UID gates remain separate CI requirements.

Fresh verification of predecessor `c11baf5` found provider, GUI, services/kernel
and Arch gates successful. General CI's Linux jobs and secret scan passed, but
macOS jobs could not acquire a hosted runner (GitHub capacity annotation); the
failed jobs were restarted. This does not count as a complete green CI run.

## Resumed native alias and HTTP matrix verification

The broker now admits exact owner model IDs and only their wire equivalents
derived by the pinned Hermes Messages normalizer. Policy checks still run on
the approved owner ID; outbound requests use the native ID. Nous Portal IDs
retain their namespace and dots. Both ingress and explicitly permitted fallback
attempts use this admission. Thirty-two real-normalizer checks cover accepted
aliases and refused models, tools, protocols and header overrides. Six native
Anthropic SDK API-key/subscription fixtures now use dotted/prefixed aliases;
two more actual HTTP calls prove per-route alias/credential isolation on fallback.

The new `probe_http_provider_matrix.py` exercises all 39 reviewed HTTP profiles
through real pinned Hermes wire builders, actual OpenAI/Anthropic clients and
the real broker. All **195** local cases pass: tool JSON, continuous early SSE
before a withheld terminal event, interrupted streams, HTTP 401 and HTTP 429.
Anthropic fixtures emit correctly named native SSE events; ledger checks wait
for actual durable finalization. Errors redact reflected keys; incomplete streams
raise in the real SDK and are never certified complete or automatically retried.
The probe is required by both the image build and provider-contract workflow.

Python 3.11.16 with the frozen SDK extras and hashed overlay passes dependency
checks. The ordinary suite passes **785 tests, two existing skips**, both with
Hermes source on PYTHONPATH and in a fresh minimal test environment without it.
Root-only backup/identity checks remain separate required CI gates. The first
local run inherited umask 0077, so a negative PKI fixture requesting mode 0755
actually created mode 0700; rerunning under CI's normal umask 0022 passes without
changing or relaxing that assertion. Ten other native/account/cloud/profile
runtime probes pass too. Source hashes and bounded receipts are archived nearby.

Fresh GitHub verification confirms all five gates at branch source `df385f5`
passed, including services/kernel run `39309865493` and its actual UID/socket/
credential tests. That PR run checked out merge source `55af1415`; its tree is
recorded separately. These historical results do not certify the new alias patch.
Full provider-specific protocol variants, gateway expansion, mobile continuous
desktop/control, phone firstboot and installed/artifact/live acceptance remain
open. No external account, inference or final release is claimed by fixtures.

## Fresh Qwen account authorization

Qwen login no longer requires a separately installed CLI or pasted refresh-token
JSON. A private native device-code/PKCE client uses the fixed official Qwen
endpoints and the pinned Hermes public client ID. Its protocol reference is
`QwenLM/qwen-code@c08007668ce01d9282ea702e95ddbc1f5adf57c9`,
`packages/core/src/qwen/qwenOAuth2.ts` (Apache-2.0). Only the checked user-code
authorization URI is printed in the protected owner terminal. Access, refresh,
device and PKCE verifier secrets stay private. A denied, cancelled, expired or
malformed response never replaces an existing credential. Successful results
are saved and subsequently refreshed by the actual pinned Hermes implementation.

Fourteen actual loopback HTTP cases verify PKCE, pending/slow-down, cancellation,
expiry, denial, untrusted authorization/resource URLs, malformed/oversized token
responses, HTTP redirect/truncation refusal and private 0600 native storage. Unit tests enforce URI and timing
limits without importing Hermes. The GUI now exposes the existing private
account-status backend without stopping execution. Native interactive Tk CI
checks its button dispatch; the root-seat/backend gate has an independent denial
test. Device authorization fixtures are required by image build and provider CI;
real Qwen account/entitlement and installed graphical login remain unaccepted.

## HTTP framing and completion receipts

An additional real-SDK regression reproduced a broker defect at `77275f1`:
syntactically valid JSON with a prematurely closed fixed-length HTTP body was
accepted because Python's bounded `HTTPResponse.read(size)` does not itself
raise for a short body. The broker now requires a consumed declared length;
catalog discovery applies the same check. SSE checks transport completion at
EOF and holds completion/stop frames until then, while continuing to forward
text/tool deltas immediately. A complete-looking terminal event followed by a
short HTTP body therefore cannot become an SDK success receipt.

The required matrix now covers **273** actual local SDK/HTTP cases (the original
195 plus JSON and terminal-SSE framing failures for each of 39 HTTP profiles).
All pass, including no retry, no unverified terminal, and unknown token counts
for failed attempts. A real truncated-catalog regression passes too. Both
minimal and full pinned-runtime suites pass **809 tests, two existing skips**;
root-only backup/UID gates remain separate CI requirements. Thirteen runtime
probes pass on these exact source inputs, without an external account or release
claim. Older 195-case receipts retain their original source hashes.

## Azure endpoint selection and complete cloud HTTP fixtures (2026-10-20)

Automatic setup now recognizes Azure's native `/anthropic` endpoint before
applying model-family defaults, in both the graphical catalog/configuration and
owner CLI. Explicit protocol selection remains available. Four setup-policy
tests and twelve more comparisons with the pinned runtime URL/model functions
cover endpoint precedence; the model-routing probe now checks 143 cases.

The new required cloud-model HTTP probe retains actual Google authorized-user
and Azure Identity/MSAL token clients, replacing only their network destinations
with local fixtures. **49** cases cover Vertex OpenAPI plus Azure Chat, Responses
and native Messages under both Entra and API-key authentication: tool JSON,
early continuous streams, aborts, 401/429, short JSON and short terminal-SSE
HTTP bodies. Native Azure version queries and cached token reuse are checked.
The shared HTTP fixtures now also exercise actual Responses and Anthropic SDK
stream accumulators, checking the final text and parsed local tool arguments
after the first delta arrives before the withheld completion.

Fresh local verification: 49 cloud cases, 273 HTTP-profile cases, 143 routing
comparisons, and **813 passed/two existing skips** in each of the minimal and
full pinned-runtime suites. The separate root-only backup/UID gates are not
counted as local passes. All five GitHub gates for predecessor `bba61f7` are
now successful, including services/kernel `39315028170`; new-source CI must
still run. Receipts are in `docs/evidence/2026-10-20`. No external account,
model inference, installed boot or final artifact acceptance is claimed.

Base: `9e432326e2c7ef56a7d9c0899ced3f53debff0ce`.
Hermes: `f97608f178d1ffeca59860195ab7da295f7c8e5f`.

`linux/haos/runtime/export_registry.py` reads the actual Hermes provider catalog,
auth registry and bundled profiles. Its data-only export contains 53 providers
(39 regular entries plus 14 registered profiles) and 22 platform adapters. The
image build regenerates and compares it, so an upstream change cannot silently
change privileged setup discovery. Root setup never imports provider plugins.
No user plugin, unknown protocol or newly installed package is automatically
authorized. Additional bundled HTTP profiles require a reviewed image/export.

| Component | Implemented here | Remaining acceptance/work |
| --- | --- | --- |
| HTTP API profiles | Registry-driven endpoint allowlists, setup/CLI, isolated credentials, three real native HTTP protocols | Provider-specific live/model/plan validation; complete per-provider quirks and dynamic discovery |
| Account providers | Native private refresh, fresh Qwen device/PKCE login, Copilot device authorization, isolated ACP login/status/local logout; physical GUI account launcher/status | Real account flows, installed GUI acceptance and remote account revocation |
| Multiple providers | Version 2 atomic migration, route-bound keys/models, GUI default/removal/fallback controls, explicit same-protocol fallback, no replay after stream starts | Installed/live failover acceptance; mixed-protocol fallback conversion is not implemented |
| Native streaming | Bounded multiline Messages, Responses and Chat Completions SSE, subscription tools, signed replay, token redaction, durable usage | External protocol/account stress and installed acceptance |
| Native Gemini | Real upstream native codec, continuous SSE, tool/signature preservation, rate/error/truncation handling | External Google account and installed acceptance |
| Cloud SDKs | IAM/bearer Converse, native Claude InvokeModel and Mantle Responses; continuous AWS EventStream and bound ordered replay; actual Google/Azure SDK token refresh/cache | Real cloud account entitlement, default-chain/role/SSO and installed live acceptance |
| Custom API | Explicit HTTPS owner route, fixed capability/model admission, private-address refusal and pinned public DNS address with original TLS hostname | Real custom endpoint acceptance and full provider-specific extension contract |
| External/virtual providers | Separate UID/Unix ACP process, secured official pinned CLI; actual upstream broker-only MoA fanout/aggregation | Real subscribed accounts, installed ACP isolation acceptance, complete reviewed external plugin admission |
| Gateways | Existing Telegram/Discord paths retained | Remaining 20 adapter integrations; no new gateway support claimed |
| Android / smartphone setup | Existing application retained | Continuous screen stream, desktop input, management, network/Wake wizard and optional firstboot page |

All provider live tests remain outstanding: no authorized provider account or
API key was supplied to this environment. Local servers emit explicit fixture
responses; they do not certify inference, subscription entitlement or billing.

Local verification of this development checkpoint:

- Actual loopback HTTP/SSE exercises all three implemented protocol families,
  tool payload/response preservation, both capability header styles, usage,
  credential reflection redaction, provider errors and incomplete streams.
- Registry-driven policy cases cover every admitted HTTP profile and reject
  endpoint substitution and provider-side computer tools.
- Real two-route transport proves that fallback uses its own key and model;
  truncated streams never dispatch to the fallback.
- Disposable root publication fixtures prove migration, independent credential
  retention, capability rotation, default selection and route revocation.
- Broad local suite before the last additions: **681 passed, 21 skipped, one
  environment-blocked failure**. AF_UNIX sockets are denied by this execution
  environment; the existing real mTLS/Unix observation test cannot bind.
  Two existing dropped-UID authority cases also cannot run here (`setuid` /
  foreign `chown` unavailable). These checks remain required in Linux CI.
- At that historical checkpoint, no QEMU, container engine, Android SDK, Xvfb or Tk was available.
  No installed boot, graphical OAuth, APK, hardware or remote-desktop acceptance
  is claimed. CI/image results must be recorded at their own exact source SHA.

No final ISO/container/APK is produced or certified by these component tests.
The remaining ordered implementation scope is tracked in Issue #2.

## Native SDK continuation

Gemini and Bedrock probes now execute the actual pinned Hermes codec/boto3
signing and CRC-checked AWS EventStream decoder against real loopback servers.
The first delta is observed before the fixture sends its terminal event. Both
probes cover function calls, secret reflection, throttling and interrupted
streams. Bedrock adapts available-byte reads instead of waiting for urllib3's
large default buffer; missing terminal events never produce `[DONE]`.

Bounded source-digest receipts are archived under `docs/evidence/2026-10-19/`.
Local runtime is Python 3.12.14; the new pinned-runtime workflow repeats these
probes on the actual image target Python 3.11 with frozen SDK dependencies and
the existing hashed security overlay. Local fixtures are not AWS/Google tests.

At commit `9875cdb4`, CI `39224402499`, services/kernel `39224402393` and Arch
packaging `39224402413` passed. These results belong to that earlier source;
they do not certify this subsequent SDK continuation. Latest local broad run,
excluding the explicitly environment-blocked remote/backup files: 670 passed,
21 existing skips. Required graphical setup, frozen-runtime, kernel, ISO/QEMU,
Android and real-account evidence remain separate.

## MoA, account refresh and dependency correction

MoA presets now resolve only owner-approved broker routes/models. The actual
unmodified Hermes MoA client completed two reference calls plus its aggregator
through the broker in a real loopback fixture, with distinct route keys and
three durable usage admissions. Fanout is deliberately bounded to the broker's
two concurrent model calls. Upstream's built-in default preset is overwritten
with an approved broker-only preset; no real provider credential enters the
agent configuration. Presets are available in the physical setup and owner CLI.

Copilot device-code login, private token exchange/expiry cache and constrained
enterprise endpoints are implemented. Qwen supports the exact upstream CLI
credential import, private persistence and native refresh. A real local refresh
probe exposed a stale Qwen pool seed in the pinned generic runtime resolver;
HAOS now calls Qwen's own refreshing resolver at this boundary. MiniMax OAuth
likewise uses its native refresh resolver. Local logout withdraws matching
routes, real keys, fallback links and dependent MoA presets before account
logout; a failure at the external account cannot silently retain a model route.

SDK source `c0e455de` passed general CI and the graphical setup render gate. Its
new frozen-provider workflow failed honestly before protocol execution:
upstream's `msal==1.36.0` requires `cryptography<49`, while the pinned runtime uses
`cryptography==50.0.0`. The reviewed compatibility overlay now pins hash-checked
`msal==1.39.0` without weakening Cryptography. A fresh Python 3.11.17 environment,
exact frozen Hermes SDK extras and the hashed overlay passed `uv pip check` and
the actual provider/Codex, native Gemini, signed Bedrock and MoA probes. The
existing red workflow is retained as historical evidence, not reported green.

Remaining provider implementation includes Copilot ACP's separately isolated
CLI runtime, model-discovery UX and remaining provider-specific protocol/plan
contracts. Provider live tests and installed acceptance remain outstanding.
Gateways and mobile desktop work remain subsequent priorities, not completed.

Current local validation for this increment: 126 provider/capability tests pass;
695 broader tests pass with 21 existing skips, excluding the two files blocked
by this host's foreign-UID and AF_UNIX restrictions. Exact Python 3.11 frozen
SDK probes (including Copilot and Qwen actual token endpoints over loopback)
pass. Their bounded receipts are the `*-python311-fixture.json` files in the
same evidence directory. They explicitly do not claim live account acceptance.

## Isolated Copilot ACP continuation

Copilot ACP now has its own system identity and private HOME, root-created
Unix socket with exact broker UID admission, independent network guard and
read-denied broker/agent/controller state. The CLI receives no other provider
keys, backend capabilities, workspace mounts, MCP servers or executable args
from a model request. Its own tools are filtered out; client filesystem,
terminal and permission requests are always refused. It cannot connect to
private/loopback services, except exact resolver/port DNS allowances.

The image builds the official Copilot CLI 1.0.98 from its reviewed SHA-256.
The actual binary accepted the secured ACP initialize handshake locally.
The pinned Hermes ACP subprocess client and upstream tool codec completed a
local protocol fixture with an early text delta before its terminal receipt,
function calls, filesystem/terminal/permission refusals and authoritative
model selection. Unknown/disabled models fail instead of silently substituting
the CLI's default. Token counts remain absent when ACP does not report usage.
Private credentials and XML bridge fragments are filtered across text deltas.

Login uses the CLI's actual device-code flow under the ACP identity. Local
logout withdraws the broker route first and removes that identity's private
Copilot state; revoking the account's remote OAuth grant remains a GitHub action.
Real subscribed-account inference is outstanding. A real kernel Unix-socket,
separate UID, socket-mode, credential-read and immediate revocation probe is
added to the required disposable-root CI; this host cannot change foreign UIDs.

At source `0e564941`, the general CI (39230128220), services/kernel
(39230128116), graphical setup (39230128170), frozen provider contracts
(39230128020) and Arch (39230128147) passed. Those receipts certify that earlier
source, not this ACP continuation. Model-discovery UX and remaining
provider-specific contracts are the next provider work. Gateways/mobile and
installed ISO/HP/real-account acceptance remain open.

## Private model discovery and route controls

The physical setup can load/search/select model IDs through a fixed private
provider process, including native Gemini and Messages pagination, the actual
Codex account-catalog parser, signed boto3 control-plane discovery and isolated
ACP session models. The root GUI never imports provider SDK/plugin code.
Keys go to the private process on stdin, never argv or public model metadata.
Catalog requests keep fixed endpoints/TLS, refuse redirects, pin custom public
DNS addresses and bound response/cursor sizes. Vertex exposes no compatible
model-list endpoint; its upstream suggestions remain explicitly offline.
All offline suggestions are distinguished from API/SDK catalogs and none is
reported as successful inference. A provider change clears previous key/URL
input before a request can be made to the new service.

Model-specific OpenCode/Go and Azure protocol rules and offline model catalogs
are generated from pinned upstream constants. A real Codex catalog fixture and
actual signed boto3 control-plane HTTP fixture pass; 109 generated routing
cases match upstream's own functions. The native setup CI now clicks model
loading/selection/configuration controls and checks credential clearing.
The GUI also exposes existing route/default/removal/ordered-fallback controls;
removal withdraws dependent MoA presets before republishing authority.

All five ACP-source gates at `a3761767` passed, including the real separate-UID
Unix socket, credential-read and route-withdrawal probe (services/kernel
39268226372); provider contracts 39268226093 and graphical setup 39268226173
also passed. These results belong to the prior ACP source. This catalog
continuation repeats them separately. Remaining provider work includes
advanced Bedrock/Mantle and native/profile contracts plus cloud SDK token-flow
fixtures; real vendor inference/account/installed acceptance is outstanding.

## Native wire profiles and cloud token flows

The agent now registers capability-only profiles through Hermes's public
provider/transport seams before starting the canonical web runtime. A read-only
owner policy supplies public routing context; it contains no provider secrets.
Only pinned pure wire-building hooks and declarative model capabilities are
projected. Original client factories, OAuth refreshers, process commands and
credential headers never enter the agent profile. The actual HTTP client stays
bound to the local broker and its scoped capability.

This preserves vendor behavior previously obscured by the broker's generic
URL: Qwen session metadata, Meta AI prompt-cache retention, and OpenRouter
reasoning replay. Fifty-three actual pinned profile cases compare native wire
kwargs or safe Messages profile admission with network access disabled. The
actual Hermes runtime resolver and three-request MoA fanout/aggregation probes
also pass with these profiles installed. Messages admission does not certify
the still-open Anthropic subscription body transforms or native Bedrock paths.

Real google-auth service-account RSA/JWT signing, authorized-user refresh, and
Azure Identity/MSAL client-credentials flows run against explicit local HTTP
fixtures, including expiry refresh and cached-token reuse. These are real SDK
protocol tests, not external account inference. Receipts with source hashes
are archived as cloud-tokens-python311-fixture.json and
wire-profiles-python311-fixture.json under evidence/2026-10-19.

Local validation: 717 tests passed and 21 existing skips, excluding the two
host-blocked foreign-UID/AF_UNIX files still required in CI. All five catalog
source gates at f8d4df8c passed, including native interactive Tk and real kernel
boundaries. Advanced Bedrock/Mantle, Anthropic subscription body contracts,
gateways, mobile desktop and installed/live-account acceptance remain open.

## Anthropic subscription and native Messages continuation

The broker applies the pinned Claude Code subscription identity, prose/tool
aliases, forced tool-choice and replay-name transforms using the real private
credential's classification. It reverses only the exact names owned by the
request before returning native JSON/SSE to the agent. API keys and third-party
Messages credentials retain their own auth behavior. Native fast-mode bodies
retain the reviewed model-gated beta. Case-insensitive SDK header merging
prevents a duplicate SDK User-Agent from preceding the subscription identity.

The public transport extension now supplies the true owner-approved endpoint
as Messages conversion context too. This preserves native signed thinking
replay without giving the agent an upstream HTTP client. All 53 projected
profile cases now compare actual native kwargs, including Messages; a separate
signed-thinking replay assertion passes with network access disabled.

The real Anthropic SDK and pinned Hermes client constructor complete six
loopback JSON/SSE cases: API key and subscription, tool alias collisions, MCP
names, forced tools, fast mode, reflected-token redaction, multiline SSE JSON
and an early delta while the upstream terminal event is deliberately withheld.
SSE framing is bounded by line/total/time and rejects incomplete final frames.
Eight parser/restoration checks and the broader suite pass: 725 tests, 21
existing skips, with the same two host-blocked files excluded locally.

The prior bb623a47 provider and GUI gates passed, but CI and services failed:
Gitleaks mistook a documented source SHA-256 for a credential, and the real
kernel fixture lacked the newly bound public policy source. The exact historical
hash finding is reviewed by commit/path/rule/line; new cloud provenance separates
paths from hashes. The kernel fixture now supplies that source and additionally
checks that it is read-only, contains no credential fields and is absent without
a model capability. No kernel gate is weakened or reported passed before rerun.
Advanced Bedrock/Mantle and external account/installed acceptance remain open.

## Three native Bedrock paths and bound Converse replay

Bedrock defaults now derive from the pinned upstream's exact Mantle model IDs
and Claude-family expression, exported as data for the root GUI. GPT-OSS stays
on Converse; the four reviewed GPT models use Responses at Mantle's fixed host
derived from the owner-approved runtime region. Claude defaults to the actual
AnthropicBedrock SDK InvokeModel/CRC-checked binary EventStream codec. Explicit
existing Claude Converse policies remain valid. A route cannot mix Mantle and
other models under one protocol allowlist.

Each route selects IAM access/secret/session keys, its private AWS profile/SDK
chain, or explicit bearer-token JSON. Bearer sessions have a route-local token
provider and an empty IAM resolver; they never consult another IAM identity or
change process-global AWS variables. Mantle uses the actual botocore signer on
the exact outbound bytes. Native Claude uses the actual SDK signer or an
explicit per-client bearer hook. The GUI documents all credential choices.

Converse JSON and streams now preserve ordered text, signed/redacted reasoning
and tool blocks through a namespaced public Hermes replay carrier. The actual
pinned ordered accumulator builds it after early deltas have already streamed.
It is bound to model and approved endpoint, and excluded by other provider
profiles. Unknown usage remains absent rather than becoming reported zero.
Native Claude streaming also retains message_start usage when SDK delta models
contain optional None fields.

Actual local fixtures cover 16 Mantle/native Claude IAM/bearer JSON, early
stream, truncation and rate-limit cases, with SigV4 verified cryptographically;
eight further real HTTP requests replay interleaved signed/redacted/tool blocks
on the next Converse turn under IAM and bearer auth. Six original Converse
cases include absent-usage handling. Generated routing comparisons include
Bedrock and all 53 wire profiles still match actual pinned kwargs. The broader
minimal-dependency test suite passes 739 cases with 21 existing skips and the
same two host-blocked files excluded. No external account or inference is used.

At cbde7f2f, provider contracts, graphical setup and general CI passed. Services
failed before the kernel probe because minimal unit fixtures do not install
Hermes: a new native-helper import ran even on ordinary non-fast local Messages.
The helper is now lazy and credential classification reuses the native client's
already emitted identity headers. All 49 minimal-dependency routing cases pass;
the real kernel test remains required and awaits the corrected-source CI.

The native MoA aggregator now streams Responses and Messages through the existing
capability-only SDK clients. The pinned auxiliary facade previously buffered
those protocols even when its caller requested streaming. A source-hash-checked
`prepare.py` overlay changes only the HAOS MoA stream dispatch; other upstream
providers retain their original dispatch. No vendor credential/client/process
hook is delegated. SDK retry is disabled and completion requires the native
terminal event plus a fully consumed HTTP body.

Seven actual pinned MoA engine/broker fixtures cover ordinary and mixed native
protocols, early output while completion is withheld, and both native stream
abortions without replay or a successful finish. Scoped SDK A→B→A checks reject
a foreign capability, unscoped access and a foreign endpoint before HTTP. Native
ordered Messages blocks and encrypted Responses items cross Hermes's actual
reasoning-detail accumulator in a model/endpoint-bound carrier; builder fixtures
verify replay and reject changed bindings or another protocol. These are local
protocol contracts, not live inference or subscription acceptance. Exact input,
derived source and test receipts: `docs/evidence/2026-10-21/moa-native-*.json` and
`moa-stream-*-fixture.json`.

## Native account-to-model and local-service continuation (2026-10-21)

The existing native device/PKCE/refresh fixtures now continue through actual
private `Credentials`, broker HTTP and pinned OpenAI/Anthropic SDK clients.
Sixty-eight additional calls cover Nous, xAI, both MiniMax regions, Qwen, Copilot,
Codex, Anthropic subscription and OpenRouter login credentials. They check local
function tools, early SSE before withheld completion, interrupted streams with
no resend, redacted 401/429 and durable ledger status/usage. Codex retains its
streamed-only native contract; these fixtures do not claim Codex JSON support.
The original login, denial, refresh, status, logout, storage and old-account
preservation assertions remain required. Native account HTTP rewrites remain
inside fixtures; SDK model clients use real loopback HTTP.

The general matrix now also executes the actual local-service/LM Studio path
without a provider key: neither Authorization nor x-api-key crosses to the local
service, and the scoped agent capability stays at the broker. All ten existing
JSON/SSE/error/framing cases apply to both profiles, for **410 cases** over 39
HTTP vendor profiles plus two local-service profiles. Both runtime variants pass
**840 tests, two existing skips**. Exact source and separate fixture receipts:
`docs/evidence/2026-10-21/account-model-http-validation.json`. Build/CI already
require the extended probes. No live account, inference or installed acceptance.

## Provider-directed retry timing (2026-10-21)

The broker previously preserved HTTP error status but discarded `Retry-After`.
It now emits sanitized public timing only on 429/503: decimal seconds or a
timezone-qualified HTTP date become 0–86400 integer seconds. Invalid, oversized,
control-character or reflected private-token values are discarded. Cookies and
other upstream error headers are not relayed. Native Google, boto3 Converse and
Anthropic-Bedrock error paths use the same timing sanitizer. This adds no retry
or prompt replay; a started or uncertain stream retains its existing refusal.

Timing resets before each approved fallback admission, including credential
lookup failures. A real HTTP regression reproduced stale timing from the first
provider leaking into the fallback's credential error during implementation;
that now passes with exactly one upstream call and no inherited header. The
410 SDK/HTTP matrix, six Gemini cases, six Converse cases and 20 native AWS
IAM/Bearer cases now assert actual Retry-After forwarding. Real local 503 and
public-date/header-negative checks pass. Both runtime suites: **860 passed, two
existing skips**. Exact source and fixture receipts are archived in
`docs/evidence/2026-10-21/provider-retry-after-validation.json` and
`*-retry-after-fixture.json`; no live-provider or installed acceptance.
