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
| Native streaming | Messages, Responses and Chat Completions SSE, local tool definitions, token redaction, durable usage | SDK/Gemini-specific streaming adapters, multiline SSE and full protocol stress matrix |
| SDK/external/virtual providers | Kept unavailable, not falsely enabled by catalog visibility | Bedrock, Vertex, Azure Foundry, Gemini, Copilot/ACP, MoA, configurable custom API and reviewed external plugin admission |
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
