# Build download compatibility

The root override pins the official `@electron/get` 5.1.0 and removes the legacy
got/cacheable-request/global-agent/roarr chain. The desktop packaging commands
explicitly preload `register.mjs` in their build process. Electron's application
runtime and ordinary global fetch are unchanged.

electron-builder 26.15.3 still passes got options. The adapter extends the official
FetchDownloader, translating its request timeout into an AbortSignal that bounds
headers **and the response body** (maximum ten minutes), retaining progress and
the existing server-error/timeout retry shape. Environment-derived proxies use
undici's documented EnvHttpProxyAgent, including NO_PROXY; differing custom
agents, unknown transport/TLS settings and unbounded deadlines are rejected.
Dispatchers are destroyed after each request, including stalled streams.

The official downloader still verifies fresh SHASUMS against downloaded/cached
archives. No TLS or checksum verification is disabled. `npm test` runs real
disposable HTTP/proxy/TLS transports, stalled headers/body, damaged checksums and
the exact packaging preload. These are local integration tests, not signed
release or external HAOS model/gateway acceptance.

Use `npm run dist:linux --workspace apps/desktop -- --x64` or `dist:mac`, which
include the adapter. Bare electron-builder invocation bypasses this compatibility
entry point and is unsupported until upstream natively migrates its options.
