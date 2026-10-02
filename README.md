# Herald OS

An agent-native desktop environment powered by [Hermes Agent](https://github.com/NousResearch/hermes-agent).

Herald OS runs on top of macOS (Apple Silicon first) and makes Hermes the primary interface
between you and your computer. It is a fullscreen environment, not a chat window: Home, Hermes,
Agents, Tasks, Skills, Files, Apps, Terminal, System and Settings surfaces, a global command bar,
and a permission-gated system bridge that lets Hermes open apps, find files, inspect processes,
stop things and organise folders on your behalf.

Herald OS does not fork Hermes. It drives whatever Hermes runtime you have installed
(`~/.hermes/hermes-agent`, kept current by `hermes update`) over its JSON-RPC and REST surface,
and adds capability as a regular out-of-tree Hermes plugin.

## Status

Alpha 0.1 for macOS. Working today against Hermes 0.21.x:

- Fullscreen shell with live system stats, notifications, sessions and streaming chat.
- Real terminal (zsh in a PTY), file browser with previews, installed-apps grid with native icons.
- Cron tasks, skills and plugins, live subagent activity, model picker, permission policy editor.
- System bridge tools: `system_info`, `system_processes`, `system_disk_usage`, `system_find_files`,
  `system_apps`, `system_open`, `system_kill_process`, `system_files`, with read / act / mutate /
  destructive tiers, protected paths, an audit trail and the standard Hermes approval card.
- Voice: talk to Hermes and hear it answer, by hotkey (`Alt+Space`), "hey hermes" wake word or the
  mic button; a free engine (any STT/TTS provider, streamed speech) and an opt-in GPT-Live engine
  with idle auto-close and a daily cap. Say "open missions", "remember that …", "pause the daily
  digest" and watch the OS do it; Hermes can drive the UI itself through the `os_ui` tool. See
  `docs/VOICE.md`.
- Studio: say "create a website for a hair salon" and watch Hermes build it in one window: the
  project's files, the code as it is written with changes marked, its commands and dev-server
  output, and a live preview.

## Requirements

- macOS 14+ on Apple Silicon (Intel builds untested).
- Node 22+.
- A Hermes Agent install: `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`.

## Run from source

```bash
npm run bootstrap     # sync the pinned upstream snapshot, npm install, link + enable the bridge plugin
npm run dev           # Vite + Electron; boots your Hermes runtime and goes fullscreen
```

`Cmd+Ctrl+F` toggles fullscreen, `Cmd+K` opens the command bar, `Cmd+1..9` switch surfaces,
`Alt+Space` starts or ends a voice conversation, `Cmd+Q` quits (and stops the backend Herald OS
started).

Useful environment variables while developing:

| Variable | Effect |
| --- | --- |
| `HERALD_OS_WINDOWED=1` | Start in a normal window instead of fullscreen |
| `HERALD_OS_HERMES_ROOT=/path/to/checkout` | Use a specific Hermes source checkout (needs its `venv/`) |
| `HERMES_HOME=/tmp/throwaway` | Sandbox away from your real Hermes home |

## Build an installer

```bash
npm run dist:mac      # arm64 DMG + zip under apps/desktop/release/
```

## Tests

```bash
npm run typecheck     # renderer, Electron main, client package
npm test              # vitest (renderer + Electron pure modules)
npm run test:bridge   # pytest for the system bridge plugin
```

## Layout

```
apps/desktop/                 Electron shell (electron/ main, preload/, src/ renderer)
packages/hermes-client/  Re-exports the upstream gateway client + generated wire contract
plugins/herald-os-bridge Hermes plugin: system bridge tools, permissions, audit, skill
plugins/tests/           pytest suite for the plugin
upstream/                UPSTREAM.lock (pinned sha) + fetched snapshot (gitignored)
docs/                    ARCHITECTURE, DECISIONS (ADRs), SYSTEM-BRIDGE, VOICE, ROADMAP, PLAN
scripts/                 bootstrap, sync-upstream, test-bridge
```

Read `docs/ARCHITECTURE.md` first, then `docs/DECISIONS.md` for the why.

## Upstream

Herald OS tracks `NousResearch/hermes-agent`. To move the pin: edit `upstream/UPSTREAM.lock`, run
`npm run sync-upstream`, then `npm run typecheck`; a changed wire field fails the build rather than
drifting silently.

MIT, like Hermes.
