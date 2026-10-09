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
indexes, traversal, oversized files and checksum changes. Raster assets are bounded
opaque bytes here; decoder/resource validation and visual regression remain open.
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

Whole-session atomic activation, independent crash watchdog/automatic rollback,
isolated graphical preview, agent generation/broker and capability-managed plugins
remain required. Saving a complete version is not autonomous theme acceptance.
