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
| Account providers | Upstream resolver/refresh dispatch; endpoint/mode mismatch denied; generic owner login/status/logout; physical GUI account launcher | Real account flows, installed GUI acceptance; fresh Qwen login/import; account revocation at provider |
| Multiple providers | Version 2 atomic migration, route-bound keys/models, default selection, removal, explicit same-protocol fallback, no replay after stream starts | GUI management of existing routes and mixed-protocol fallback conversion |
| Native streaming | Messages, Responses and Chat Completions SSE, local tool definitions, token redaction, durable usage | Multiline SSE and full protocol stress matrix; additional provider-specific contracts |
| Native Gemini | Real upstream native codec, continuous SSE, tool/signature preservation, rate/error/truncation handling | External Google account and installed acceptance |
| Cloud SDKs | boto3 Converse signing + continuous AWS EventStream; Vertex service-account/ADC token refresh; Azure API-key/service-principal/default-chain token handling and native Messages query/header handling | Bedrock Mantle/OpenAI path and advanced native reasoning replay; real SDK account entitlement and cloud live tests |
| Custom API | Explicit HTTPS owner route, fixed capability/model admission, private-address refusal and pinned public DNS address with original TLS hostname | Real custom endpoint acceptance and full provider-specific extension contract |
| External/virtual providers | Remain unavailable rather than dropdown-only support | Copilot/ACP, MoA, fresh Qwen login/import and complete reviewed external plugin admission |
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
