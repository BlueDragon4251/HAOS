# Themes

Maintained Herald schema/implementation remains in apps/desktop/shared/theme.ts, electron/theme and linux/bin/herald-os-theme. Existing interface tests do not prove autonomous generation or crash rollback.

The isolated agent cannot directly mutate observer theme/session files. A restricted broker must validate data/assets/capabilities, test in isolation, atomically activate complete versions and recover the previous one with an independent watchdog.

Native and Linux data validation now rejects unknown/executable fields, path escapes, unsafe configuration values, control characters, malformed terminal palettes and non-hex colors. Theme loading rejects symlinked manifests/directories/assets and oversized files. These are specific import protections, not proof of whole-theme transaction or crash recovery.

Executable plugins are not harmless theme data and never inherit owner authority. Manifest/locked-dependency/revocation and malicious-theme acceptance remain required.

## Complete saved revisions

Native save and Git import now publish complete bundles under
`~/.config/herald-os/theme-versions/<name>/<sha256>/`. The unchanged `theme.json`
data schema remains authoritative. SHA-256 covers the exact manifest bytes, a NUL
separator and the wallpaper bytes (empty for the drawn wallpaper). This detects
changed bytes; it is not a signature or protection against the storage owner.

The publisher writes and fsyncs an isolated staging directory, renames the complete
bundle, verifies it again, then replaces/fsyncs `current.json`. Existing revisions
are never overwritten or deleted by this API. Failed staging/index publication
preserves the prior index; an index or revision that fails validation is unavailable,
without silently choosing a legacy copy. Built-in names remain protected. Existing
legacy folders and unrelated user files remain untouched.

Readers reject unsafe directories, manifest/asset symlinks and hardlinks, malformed
indexes, traversal, oversized files and checksum changes. The store itself treats
raster assets as bounded opaque bytes; the separate renderer gate below decodes them.
The native and actual Linux readers share the checksum contract. Applying an exact
revision preserves its wallpaper location and saves its identifier in native prefs
and the Linux marker, including compositor regeneration after a missing config.
Appearance offers verified saved versions; the recovery CLI accepts
`herald-os-theme set <name> --revision <sha256>`.

Tests exercise real filesystem publication, injected index-write failure, restart,
retained old assets/legacy files, corrupt manifests/assets and symlink/hardlink attacks.
A cross-language test runs the real Linux loader and renders the old version's
actual niri/GTK/terminal/skin configuration into an isolated home. Desktop relay and
gsettings are disabled in that fixture; it proves no running compositor or model.

## Actual isolated preview and preactivation gate

Appearance's Preview action renders the verified bundle with the production-built
renderer stylesheet and the actual palette/preset rules. It returns an actual
960×640 Chromium screenshot, its SHA-256, the stylesheet SHA-256 and explicit
render/visibility/contrast/raster/isolation results. New saved revisions must pass
this gate before native preferences or the Linux theme command are changed. A
failed preview leaves the previous selection in use; the saved draft remains
available. Built-in/legacy selection retains its existing behavior.

Each preview has an ephemeral Electron session, no preload or Node access,
enabled Chromium sandbox, denied permissions/downloads/navigation/new windows and
a network-denying CSP/request filter. Linux also requires the actual renderer's
`/proc` status to attest NoNewPrivs, seccomp and zero effective capabilities.
Only one preview runs at a time, with a 15-second deadline. Labels are escaped;
theme data cannot supply scripts, CSS or arbitrary file/HTTP URLs. Wallpapers are
read from the checked bundle and decoded as data images in this isolated renderer.
Successful decode requires dimensions at most 8192 each and at most 16M pixels;
this post-decode check is not a preallocation memory bound. Complete resource
budgeting and broader decoder-security validation remain open.

Contrast uses the actual composed glass-card background as well as the body and
control colors. This is a representative fixture, explicitly labeled as a preview,
not an executing mission or proof that every shell/compositor window is usable.
There is no golden-image regression baseline yet.

After `npm run build`, run on disposable Linux fixtures as a non-root user:

```sh
HAOS_DISPOSABLE_SCREEN_TEST=1 npm run test:theme-preview --workspace @herald-os/desktop
```

The gate uses real headless Chromium, not mocked screenshots. It exercises escaped
markup with a real HTTP canary (zero requests), actual PNG decode, unreadable body
text, unreadable glass-card text and corrupt raster rejection. It preserves an old
verified revision and writes only disposable fixture screenshots and a receipt
with the exact Git source/dirty status and Electron/Chromium versions. Linux CI
requires this gate and retains its narrow evidence for seven days. Its launcher
gets an exact-path user-namespace AppArmor permission on the disposable runner;
AppArmor and the renderer sandbox remain enabled.

Whole-session atomic activation, independent crash watchdog/automatic rollback,
agent generation/broker and capability-managed plugins remain required. Saving
and previewing complete versions is not autonomous theme acceptance.
