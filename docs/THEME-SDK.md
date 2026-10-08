# Themes

Maintained Herald schema/implementation remains in apps/desktop/shared/theme.ts, electron/theme and linux/bin/herald-os-theme. Existing interface tests do not prove autonomous generation or crash rollback.

The isolated agent cannot directly mutate observer theme/session files. A restricted broker must validate data/assets/capabilities, test in isolation, atomically activate complete versions and recover the previous one with an independent watchdog.

Native and Linux data validation now rejects unknown/executable fields, path escapes, unsafe configuration values, control characters, malformed terminal palettes and non-hex colors. Theme loading rejects symlinked manifests/directories/assets and oversized files. These are specific import protections, not proof of whole-theme transaction or crash recovery.

Executable plugins are not harmless theme data and never inherit owner authority. Manifest/locked-dependency/revocation and malicious-theme acceptance remain required.
