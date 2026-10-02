# herald-os-bridge

The Hermes plugin that lets Hermes act on the computer and drive the Herald OS interface. It is a
regular out-of-tree plugin: Hermes loads it from `$HERMES_HOME/plugins/herald-os-bridge`, a link
`npm run bootstrap` creates to this folder. Nothing in the Hermes core is patched.

Tools, permission tiers, protected paths, the policy file and the audit log are documented in
[docs/SYSTEM-BRIDGE.md](../../docs/SYSTEM-BRIDGE.md).

```
__init__.py          register(): the `herald_os` toolset and the bundled skill
plugin.yaml          manifest: name, version, tools, supported platforms
bridge/
  tools.py           tool schemas and handlers (TOOL_SPECS)
  permissions.py     tiers, protected paths, the approval gate
  audit.py           one JSON line per call in $HERMES_HOME/herald-os/audit.jsonl
  ui.py              client for the shell's control socket (the `os_ui` tool)
  util.py            shared helpers (data folder, HERALD_OS_* settings)
  host/              HostAdapter per OS: darwin.py, linux.py, posix.py, windows.py (stub)
skills/herald-os/    SKILL.md, the skill that teaches Hermes when to use these tools
tests/               pytest suite: `npm run test:bridge` from the repository root
```

## Enabling it by hand

`npm run bootstrap` does all of this. Without it:

```bash
ln -s "$PWD/plugins/herald-os-bridge" ~/.hermes/plugins/herald-os-bridge
hermes plugins enable herald-os-bridge
hermes tools enable herald_os
```

To switch the tools off without uninstalling, set `herald_os.bridge.enabled: false` in
`~/.hermes/config.yaml`, or `HERALD_OS_BRIDGE_DISABLED=1` in the backend's environment for one run.
