<p align="center">
  <img src="apps/desktop/build/icon.png" alt="Herald OS" width="112">
</p>

<h1 align="center">Herald OS</h1>

<p align="center">
  An agent-native desktop environment powered by <a href="https://github.com/NousResearch/hermes-agent">Hermes Agent</a>.
</p>

<p align="center">
  <a href="https://github.com/iamlukethedev/Herald-OS/actions/workflows/ci.yml"><img src="https://github.com/iamlukethedev/Herald-OS/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
</p>

Herald OS is a fullscreen environment that makes Hermes the main way you use your computer. You
talk or type to Hermes, and it works on your machine: it opens apps, finds and organises files,
watches what is running, remembers what matters to you, runs routines on a schedule, and builds
software while you watch. Every action that changes something goes through a permission system you
control.

It runs on macOS today, and as its own Linux session (Herald OS Linux, in development). Herald OS
does not fork Hermes: it drives the Hermes install you already have and adds desktop abilities as a
regular Hermes plugin.

> **Status: alpha (0.1).** Expect rough edges, and keep backups of anything you let an agent
> touch.

## What you get

- **Overview, Hermes, Missions, Memory, Files, Automations, Connections and Settings** pages, plus a
  Terminal, a System monitor, and floating chat windows.
- **A command bar** (`Cmd+K`) for every action in the OS: open pages and apps, add memories, run
  automations, start missions.
- **Desktop tools for Hermes**: system info, processes, disk usage, file search, opening apps,
  moving and trashing files, and more, each with a permission tier, protected paths, an audit log
  and the standard Hermes approval card. See [docs/SYSTEM-BRIDGE.md](docs/SYSTEM-BRIDGE.md).
- **Voice**: press `Alt+Space` or say "hey Hermes" and talk. Hermes answers out loud and can operate
  the interface ("open missions", "remember that my sister's birthday is in May"). A free engine
  works with any speech provider; an opt-in realtime engine is available. See
  [docs/VOICE.md](docs/VOICE.md).
- **Studio**: say "build a website for a hair salon" and watch it happen in one window: the
  project's files, the code as it is written, the commands it runs, and a live preview.

## Requirements

- **macOS 13 (Ventura) or later on Apple Silicon.** Intel Macs are untested. Herald OS is
  developed on macOS 26.
- **Node.js 22.12 or later** ([nodejs.org](https://nodejs.org), or `brew install node`).
- **Git**, and the Xcode Command Line Tools (`xcode-select --install`) for native modules.
- **Hermes Agent 0.21.3 or later**, with a model provider set up (step 1 below).

## Getting started

### 1. Install Hermes Agent and choose a model

Herald OS uses your own Hermes install. If you don't have it yet:

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
source ~/.zshrc
hermes setup
```

`hermes setup` walks you through choosing a model provider (Nous Portal, OpenRouter, OpenAI, a
local model, and others) and signing in. You can change it later with `hermes model`, or from
Herald OS under Settings.

Check that Hermes works on its own before going further:

```bash
hermes doctor
hermes        # say hello, then exit with Ctrl+D
```

### 2. Get the code

```bash
git clone https://github.com/iamlukethedev/Herald-OS.git
cd Herald-OS
```

### 3. Bootstrap

```bash
npm run bootstrap
```

This is safe to re-run, and you should re-run it after every `git pull`. It:

1. downloads the pinned Hermes gateway client the shell is compiled against (`upstream/`);
2. installs the Node packages and downloads Electron;
3. links the `herald-os-bridge` plugin into `~/.hermes/plugins` and enables it and its tools;
4. migrates settings from the project's earlier name (Hermes OS), if you had it installed;
5. reports which optional voice packages your Hermes install has.

### 4. Start Herald OS

```bash
npm run dev
```

Herald OS starts your Hermes runtime in the background (`hermes serve`, on 127.0.0.1 only), shows
the boot screen, and goes fullscreen. `Cmd+Ctrl+F` leaves or re-enters fullscreen; `Cmd+Q` quits
and stops the backend it started.

Edits to the interface (`apps/desktop/src`) reload live. Changes to the Electron main process need
a restart (`Ctrl+C`, then `npm run dev` again).

### 5. Check that everything works

- **Hermes answers.** Open the Hermes page (`Cmd+2`) and ask something. If it asks you to sign in,
  use the card it shows, or run `hermes setup` again.
- **Desktop tools work.** Ask "what is using the most memory right now?". Hermes should answer with
  the `system_processes` tool rather than a shell command. Ask it to move a file and you should get
  an approval card first.
- **Voice works (optional).** Press `Alt+Space` and allow microphone access when macOS asks.
  Settings > Voice has "Say hello" and "Start talking" buttons to test it.

## Using Herald OS

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Cmd+K` | Command bar |
| `Cmd+1` ... `Cmd+7` | Overview, Hermes, Missions, Memory, Files, Automations, Connections |
| `Cmd+,` | Settings |
| `Cmd+8`, `Cmd+9` | Terminal, System |
| `Cmd+Shift+A` | All applications (Herald OS apps and your Mac's apps) |
| `Cmd+\` | Show or hide the sidebar |
| `Alt+Space` | Start or end a voice conversation, from any app (change it in Settings > Voice) |
| `Cmd+Ctrl+F` | Toggle fullscreen |
| `Cmd+Q` | Quit |

### Permissions

Hermes's desktop tools have four tiers. `read` tools (system info, file search) and `act` tools
(opening an app) run straight away and are logged. `mutate` tools (create, move, rename) ask first,
and you can allow them for the session or always. `destructive` tools (stopping a process, moving
files to the Trash) ask every time. Some locations, such as `~/.ssh`, your keychains and Hermes's
own credentials, are always refused.

Settings > Privacy shows the policy and the audit log (`~/.hermes/herald-os/audit.jsonl`). Hermes's
own terminal tool keeps following Hermes's approval settings.

### Settings and data

| What | Where |
| --- | --- |
| Herald OS preferences | `~/.hermes/herald-os/prefs.json` (edit them in Settings) |
| Audit log, control socket | `~/.hermes/herald-os/` |
| Log file | `~/.hermes/logs/herald-os.log` |
| Hermes config, memories, sessions, credentials | `~/.hermes/`, managed by Hermes |

A few options come from environment variables, mostly for development: starting windowed
(`HERALD_OS_WINDOWED=1`), using a different Hermes checkout (`HERALD_OS_HERMES_ROOT`), or a
throwaway Hermes home (`HERMES_HOME=/tmp/herald-test`). [.env.example](.env.example) lists them
all.

## Building the app

```bash
npm run dist:mac
```

This writes an Apple Silicon DMG and zip to `apps/desktop/release/`. Before installing, know that:

- **The build is unsigned.** macOS will refuse to open it the first time: right-click the app and
  choose Open, or run `xattr -dr com.apple.quarantine "/Applications/Herald OS.app"`.
- **macOS notifications need a signed build.** Notifications still appear inside Herald OS, but the
  macOS ones it sends while you are in another app only work when the app is code-signed.
- **The desktop tools plugin is not bundled.** Run `npm run bootstrap` from a checkout once so
  Hermes loads `herald-os-bridge`.
- **Hermes Agent is not bundled either.** The app finds it as in development:
  `HERALD_OS_HERMES_ROOT`, then `~/.hermes/hermes-agent`, then `hermes` on your PATH.

## Herald OS Linux

Herald OS Linux turns the shell into a whole session: greetd logs you in, niri manages windows, and
the shell draws the menu bar, dock and notifications. It is in development and runs in a Fedora VM
on Apple Silicon:

```bash
bash linux/vm/download-image.sh && bash linux/vm/make-seed.sh && bash linux/vm/run-qemu.sh
```

[linux/README.md](linux/README.md) has the full walkthrough and [docs/LINUX.md](docs/LINUX.md) the
details.

## Project layout

```
apps/desktop/               The shell: Electron main (electron/), preload/, React renderer (src/)
packages/hermes-client/     Typed client for the Hermes gateway (JSON-RPC over WebSocket, REST)
plugins/herald-os-bridge/   Hermes plugin: desktop tools, permission tiers, audit log, UI control
linux/                      Herald OS Linux: session, niri config, provisioning, VM tooling
scripts/                    bootstrap, upstream sync, bridge tests, secret scan
upstream/                   UPSTREAM.lock, the pinned Hermes version the shell builds against
docs/                       architecture, decisions, system bridge, voice, Linux
```

New here? Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), then
[apps/desktop/README.md](apps/desktop/README.md) for where things go in the shell.

## Development

```bash
npm run typecheck     # TypeScript: renderer, Electron main and preload, client package
npm test              # Vitest
npm run test:bridge   # pytest for the bridge plugin
npm run build         # production build into apps/desktop/dist
bash scripts/check-secrets.sh   # gitleaks over the history and your changes
```

CI runs all of these on Ubuntu and macOS. [CONTRIBUTING.md](CONTRIBUTING.md) has the conventions.

## Updating

```bash
git pull
npm run bootstrap
hermes update         # Hermes itself, whenever you like
```

The shell compiles against a pinned Hermes version (`upstream/UPSTREAM.lock`), so updating Hermes
does not change the shell's code. Moving the pin is described in [upstream/README.md](upstream/README.md).

## Troubleshooting

- **"No Hermes runtime found", or the boot screen never finishes.** Run `hermes doctor`. If Hermes
  lives somewhere other than `~/.hermes/hermes-agent` and is not on your PATH, start with
  `HERALD_OS_HERMES_ROOT=/path/to/hermes-agent npm run dev`. The cause is usually in
  `~/.hermes/logs/herald-os.log`.
- **Hermes uses shell commands instead of its desktop tools.** Re-run `npm run bootstrap`, then
  restart Herald OS. `hermes plugins list` should show `herald-os-bridge` as enabled.
- **`npm run dev` waits on a download.** Electron downloads itself on first use. Bootstrap does this
  up front; behind a proxy, see [Electron's installation docs](https://www.electronjs.org/docs/latest/tutorial/installation).
- **Native module errors after changing Node versions.** Delete `node_modules` and run
  `npm run bootstrap` again.
- **The microphone does nothing.** Check System Settings > Privacy & Security > Microphone. In
  development the permission belongs to Electron (or your terminal); in the built app, to Herald OS.
- **Stuck fullscreen.** `Cmd+Ctrl+F`, or start with `HERALD_OS_WINDOWED=1 npm run dev`.

## Contributing and security

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Please report vulnerabilities
privately, as described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Herald OS builds on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by
Nous Research, also MIT; see [NOTICE](NOTICE).
