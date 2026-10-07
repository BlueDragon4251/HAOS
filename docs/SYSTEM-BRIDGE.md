# System Bridge

The system bridge is how Hermes acts on the computer. It is a Hermes plugin
(`plugins/herald-os-bridge`) that registers a small toolset named `herald_os`. Every capability is
an explicit tool with a typed schema, a permission tier, and an audit record. The model never gets
unrestricted machine access.

## Tools

| Tool | Tier | Purpose |
| --- | --- | --- |
| `system_info` | read | OS version, hardware, uptime, CPU load, memory, disks, battery |
| `system_processes` | read | Top processes by CPU or memory, find by name, find by listening port |
| `system_disk_usage` | read | Largest entries under a directory (bounded depth and time) |
| `system_find_files` | read | File search (Spotlight on macOS, `plocate`/`fd` on Linux): name, kind, screenshots, date ranges, scope |
| `system_apps` | read | Installed applications and currently running applications |
| `system_network` | read | Connectivity (interfaces, gateway, DNS, Wi-Fi link) and Bluetooth devices |
| `system_logs` | read | Recent lines from the system log, filtered by level and process; recent crashes and one crash's facts (macOS crash reports, Linux core dumps) for the `diagnose-crash` skill |
| `system_control` | read / act / mutate | Volume, dark mode, notifications, System Settings panes, display sleep, screen lock; switching Wi-Fi asks first. On Herald OS Linux also Wi-Fi networks and joining one (asks first), Bluetooth power (asks first) and devices, the sound output, brightness and the power mode |
| `system_open` | act | Open an app, URL, file or folder; reveal in Finder; open a path in an editor |
| `system_kill_process` | destructive | Terminate a process by pid or by listening port |
| `system_files` | mutate / destructive | Create folders, move, rename, trash (never `rm`). `dry_run` plans say where each item lands and list clashes (nothing is ever overwritten, and a batch is checked before anything moves); applied moves and copies return `undo` operations |
| `system_documents` | read | Read PDFs page by page (scans and photos of documents through on-device OCR) with hints for filing: kind, vendor, dates, number, total, a suggested name and a fingerprint for duplicates; `places` lists the folders documents are already filed in, with their layout and naming. Used by the `file-documents` skill |
| `os_ui` | per command | Operate the Herald OS interface: open pages and apps, add memories, run automations, start missions and Studio builds. Each command carries its own tier |
| `system_os` | act / mutate | Herald OS Linux only: install apps and anything in the install catalog (`catalog_list`, `catalog_install`, `catalog_remove`), widget plugins (`plugin_list`, `plugin_add`, `plugin_update`, `plugin_disable`, `plugin_remove`; turning one on is left to the user), reminders, themes, screenshots, lock, suspend, update |

"Start my development environment" is a skill: it composes `system_open` with Hermes's existing
`terminal` tool rather than adding another core-shaped tool.

## Documents

"Find the invoice from Acme in my Downloads, rename it properly and put it where it belongs" is the
`file-documents` skill: `system_documents action=read` on the folder, `system_documents
action=places` for where such files already live, one `system_files` batch run as a dry run, the
approval card, and the result's `undo` if the person changes their mind.

- Text: on macOS PDFKit reads each page's text layer and Vision recognises the text of scanned pages
  and images (both through a JavaScript-for-Automation script, as the shell's screen-text reader
  does; nothing is installed). On Linux `pdftotext` reads text when poppler-utils is installed,
  otherwise the Hermes runtime's own converter (anydoc) or pypdf; tesseract reads scans, from pages
  rendered by `pdftoppm` or, without poppler, from the pictures the scan is made of (JPEG, Flate,
  CCITT fax).
- Limits per call: 15 documents (50 at most), 3 pages each (20 at most), files up to 50 MB, about two
  minutes of reading; what is left over comes back under `skipped` for the next call.
- Hints are heuristics: the document's kind (invoice, receipt, statement, quote, credit note, payslip,
  contract, order), the vendor (never the bill-to customer), the issue and due dates (`date_ambiguous`
  when day and month could swap), the invoice or receipt number and the total with its currency.
- Nothing leaves the computer: no hosted OCR is used.

## Where the tools run

Only in sessions Herald OS starts. Hermes turns a plugin's toolset on for every platform that has not
saved a list without it, and Herald OS's backend shares the `cli` platform's list with the `hermes`
CLI, so the configuration alone would hand these tools to the person's Telegram, Discord, cron and
terminal sessions as well. The plugin decides from the session instead (`bridge/scope.py`):

- **Every call is checked.** A tool runs only when the source Hermes binds for the turn
  (`HERMES_SESSION_SOURCE`) is `herald_os`, or `hermes_os` for sessions from before the rename. Any
  other call is refused with `decision: outside_herald` and recorded in the audit log. This holds
  whatever the toolset configuration says and whichever process loaded the plugin, a messaging
  gateway started by Herald OS's backend included.
- **The model only sees them there.** The tools' availability check hides them from turns of every
  other surface (a messaging platform, the API server, cron, the TUI, Hermes Desktop) and, in
  processes Herald OS did not start, from anything but a Herald OS turn. Herald OS's own backend
  keeps them listed while it builds or refreshes an agent between turns. The check is not cached, so
  one session's answer never reaches another.
- **Nothing to do on existing installs.** The toolset can stay enabled on every platform; outside
  Herald OS it is inert. The bundled skills stay readable everywhere, and without the tools they
  change nothing.

`herald_os.bridge.enabled: false` in `config.yaml` (or `HERALD_OS_BRIDGE_DISABLED=1`) hides the tools
and refuses their calls everywhere, Herald OS sessions included.

## Permission tiers

| Tier | Behaviour | Examples |
| --- | --- | --- |
| `read` | Runs immediately, audited | info, processes, disk usage, search |
| `act` | Runs immediately, audited, surfaced as a notification | open Safari, open a repo in VS Code |
| `mutate` | Requires confirmation; `session` and `always` are honoured | mkdir, move, rename |
| `destructive` | Always requires confirmation; per-call rule key so `always` cannot persist | kill process, trash files |

Confirmation goes through upstream's `tools.approval.request_tool_approval`, which the shell
renders as its approval card. `approvals.mode: off` and yolo mode are honoured exactly as they are
for shell commands, because it is the same gate.

## Enabling

Three setups make the same changes: `npm run bootstrap` for a checkout, the app's first start for a
packaged build, and `herald-os setup` for the Linux packages. Each links the plugin into
`$HERMES_HOME/plugins/herald-os-bridge`, then runs `hermes plugins enable herald-os-bridge`,
`hermes tools enable herald_os` (a saved platform toolset list is authoritative upstream), and
`hermes config set tools.tool_search.enabled off` so the tools are directly callable rather than
deferred behind Hermes's tool-search bridge (see `DECISIONS.md`, ADR-010). Each says what a step
changes and stops at the first `hermes` step that fails, counting the `✗` line `hermes tools enable`
prints with exit 0 for an unknown toolset: the terminal setups print Hermes's output and exit
non-zero; the app shows a notification and a note under Settings > Hermes & agents > Tool search,
and tries again at its next start. Settings -> Privacy edits the policy file below and shows the
audit log.

## What Herald OS changes in your Hermes

Herald OS runs on the person's own Hermes, so these changes reach Hermes's other sessions too:

| Change | Made by | Outside Herald OS |
| --- | --- | --- |
| The link `$HERMES_HOME/plugins/herald-os-bridge` | setup | Inert until the plugin is enabled |
| `herald-os-bridge` in `plugins.enabled` | setup | Hermes loads the plugin everywhere; its tools stay hidden and refuse to run (see Where the tools run) |
| `herald_os` in `platform_toolsets.cli`; `hermes tools enable` saves the whole `cli` list, with `known_plugin_toolsets` and `known_builtin_toolsets` | setup | The `hermes` CLI uses the same list |
| `tools.tool_search.enabled: off`, the value before kept in `$HERMES_HOME/herald-os/tool-search-before` | setup; Settings > Hermes & agents > Tool search turns it back on | Every session lists its plugin and MCP tools directly instead of searching for them |
| `display.skin: herald-os` and `$HERMES_HOME/skins/herald-os.yaml` | applying a theme, unless another skin was chosen | Hermes's own interfaces wear the theme |
| `stt.provider: local`, `tts.provider: edge` | the voice fallback, when the configured provider cannot run (no key, a missing package), with a notice | Every voice surface uses the free provider |

The record of Tool Search's earlier value is written once, before the first change, by whichever
setup makes it; setups before it existed kept none.

**Undo.** `herald-os setup --undo` turns the toolset off while Hermes still knows it, then the
plugin, puts Tool Search back to the recorded value when it is still off (to Hermes's default, `auto`,
when there is no record), removes the link, and writes the app's `bridge-enabled` marker so the app
does not set it all up again. By hand, on macOS:

```bash
hermes tools disable herald_os
hermes plugins disable herald-os-bridge
hermes config set tools.tool_search.enabled "$(cat ~/.hermes/herald-os/tool-search-before 2>/dev/null || echo auto)"
rm -f ~/.hermes/plugins/herald-os-bridge ~/.hermes/herald-os/tool-search-before
touch ~/.hermes/herald-os/bridge-enabled
```

What stays: the `cli` toolset list remains an explicit saved list, and the plugin is listed under
`plugins.disabled`. `hermes config set display.skin default` brings back Hermes's own skin, and
`hermes tools` or Settings > Voice picks the speech providers. To set the bridge up again, run
`herald-os setup`, or on macOS delete `~/.hermes/herald-os/bridge-enabled` and start Herald OS.

## Protected paths

Operations that would read or modify these locations are refused before any approval prompt:

- secrets: `~/.ssh`, `~/.gnupg`, `~/Library/Keychains`, `~/Library/Cookies`, `$HERMES_HOME/.env`,
  `$HERMES_HOME/auth.json`;
- system folders: `/System`, `/Library`, `/usr`, `/bin`, `/sbin`, `/etc`, `/private/etc`,
  `/var/db`, `/private/var/db`, and on Linux `/boot`, `/lib`, `/lib64`, `/var/lib`, `/proc`, `/sys`.

The list is extended (never shortened) in the policy file. The built-in list is
`BUILTIN_PROTECTED` in `bridge/permissions.py`.

## Policy file

`$HERMES_HOME/herald-os/permissions.yaml`

```yaml
version: 1
tiers:
  read: allow          # allow | confirm | deny
  act: allow
  mutate: confirm
  destructive: confirm # cannot be set to allow
protected_paths:
  - ~/Documents/Taxes
```

## Audit log

Every tool invocation appends one JSON line to `$HERMES_HOME/herald-os/audit.jsonl`:
`{ts, tool, tier, action, args, decision, ok, error}`. Arguments are truncated; no file contents are
logged (`system_documents` records the paths it was given, never the text it read).

## Platform abstraction

`bridge/host/base.py` defines `HostAdapter`. `darwin.py` implements it with `mdfind`, `open`,
`lsof`, `ps`, `osascript` (PDFKit and Vision for documents), `system_profiler`, `vm_stat`;
`linux.py` with `ps`, `ss`, `plocate`/`fd`, `gio`, `xdg-open`, `nmcli`, `bluetoothctl`, `wpctl`,
`gsettings`, `journalctl`, and `pdftotext`/`tesseract` for documents (shared POSIX parts live in
`posix.py`; the document hints, the scan-picture reader and the filing-place scan in
`bridge/documents.py`). `windows.py` raises `HostNotSupported` with a clear message. The adapters
exist so the tool layer never branches on `sys.platform`.

## Tests

`npm run test:bridge` runs the plugin's pytest suite (`plugins/herald-os-bridge/tests`) with the
Hermes runtime's interpreter, or in a throwaway `uv` environment if that interpreter has no pytest.
