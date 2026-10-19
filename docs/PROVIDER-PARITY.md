# Hermes parity work — development, not release acceptance

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
| Account providers | Native private refresh, Qwen CLI import, Copilot device authorization, isolated ACP login/status/local logout; physical GUI account launcher | Real account flows, installed GUI acceptance and remote account revocation |
| Multiple providers | Version 2 atomic migration, route-bound keys/models, default selection, removal, explicit same-protocol fallback, no replay after stream starts | GUI management of existing routes and mixed-protocol fallback conversion |
| Native streaming | Messages, Responses and Chat Completions SSE, local tool definitions, token redaction, durable usage | Multiline SSE and full protocol stress matrix; additional provider-specific contracts |
| Native Gemini | Real upstream native codec, continuous SSE, tool/signature preservation, rate/error/truncation handling | External Google account and installed acceptance |
| Cloud SDKs | boto3 Converse signing + continuous AWS EventStream; Vertex service-account/ADC token refresh; Azure API-key/service-principal/default-chain token handling and native Messages query/header handling | Bedrock Mantle/OpenAI path and advanced native reasoning replay; real SDK account entitlement and cloud live tests |
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
- This environment has no QEMU, container engine, Android SDK, Xvfb or Tk.
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
