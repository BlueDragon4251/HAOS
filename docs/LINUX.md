# Hermes OS Linux (Stage 1)

Hermes OS as the whole desktop of a Linux machine: a Fedora base, `cage` as the Wayland compositor,
the Electron shell as the only session, Hermes Agent underneath. Stage 1 runs in a virtual machine
on your Mac; nothing on the Mac changes.

```
kernel + systemd  ->  greetd (autologin: hermes)  ->  cage  ->  Hermes OS shell  ->  hermes serve
                                                                      |                    |
                                                          HostPlatform (linux.ts)   hermes-os-bridge (LinuxHost)
                                                                      \__________  ps ss nmcli wpctl gio journalctl plocate
```

## Quick start (QEMU, all from the terminal)

```bash
brew install qemu                       # once
bash linux/vm/download-image.sh         # Fedora Cloud Base aarch64 qcow2 (~500 MB)
bash linux/vm/make-seed.sh              # cloud-init seed + SSH key (linux/vm/build/)
bash linux/vm/run-qemu.sh               # boots; first boot provisions (5-10 min)
bash linux/vm/run-qemu.sh console       # watch cloud-init / provisioning
bash linux/dev/push.sh --with-hermes-config   # push repo, build shell, copy Hermes credentials
```

A QEMU window appears on the Mac. After provisioning and the first push, the VM reboots into the
Hermes desktop with no login prompt. `bash linux/vm/run-qemu.sh stop|status|reset` manage it.

Window size: QEMU shows guest pixels 1:1 with the Mac's device pixels. The default framebuffer is
2048x1280 (`GUEST_W`/`GUEST_H`) with the shell zoomed 1.5x (`HERMES_OS_SCALE` in `session.env`),
about 1024x640 points on a Retina display. For a bigger window use e.g. `GUEST_W=2880 GUEST_H=1800`
with `HERMES_OS_SCALE=2`, or pick View -> Zoom To Fit in QEMU's menu and resize/fullscreen the
window (toggle it after boot; enabling it at launch makes the guest adopt the initial window size).

`--with-hermes-config` copies `~/.hermes/{config.yaml,.env}` (model choice and any API keys) into
the VM. It deliberately does not copy `auth.json`: OAuth providers (Nous Portal, Codex, Copilot)
use rotating refresh tokens, so a copied login works only until the next refresh and whichever
machine refreshes second is logged out. Log the VM in on its own instead:

```bash
bash linux/dev/push.sh ssh
hermes login          # device-code flow; open the URL on the Mac
```

(`--with-hermes-auth` copies `auth.json` anyway, for short experiments where that trade-off is fine.)

## Quick start (UTM, a nicer window)

1. `brew install --cask utm`. Run `download-image.sh` and `make-seed.sh` as above.
2. UTM: Create a New Virtual Machine, Virtualize, Linux. Tick "Use Apple Virtualization".
   Boot from `linux/vm/build/fedora-cloud-44-aarch64.qcow2` (import the disk; UTM converts it).
   4 cores, 8 GB, "Enable hardware OpenGL acceleration".
3. Add a second drive from `linux/vm/build/cidata.iso` (read-only, removable).
4. Sharing: add a VirtioFS shared directory pointing at this repo, tag `hermes-os`.
5. Network: emulated VLAN with a port forward, guest 22 -> host 2222 (or use Bridged and set
   `HERMES_VM_HOST=<vm-ip>` for the scripts).
6. Boot. cloud-init mounts the share at `/mnt/hermes-os`, provisions, builds the shell from the
   share, and greetd starts the desktop. Later, inside the VM, `hermes-os-sync` re-syncs and
   rebuilds from the share; from the Mac `bash linux/dev/push.sh` works too.

## What provisioning does (`linux/provision.sh`)

- SELinux permissive (greetd + cage have no tailored policy yet; Stage 2 writes one).
- `dnf install`: cage, greetd, seatd, PipeWire, NetworkManager, BlueZ, UPower, portals,
  Electron runtime libraries, fonts, Node.js + toolchain, and the CLI tools the Linux adapters use
  (`xdg-utils`, `gio`, `plocate`, `fd`, `rsvg-convert`, `notify-send`, `grim`), plus Firefox,
  Nautilus, Text Editor and `foot` as a rescue terminal.
- Hermes Agent cloned to `~/.hermes/hermes-agent` at the revision in `upstream/UPSTREAM.lock`,
  installed with upstream's `setup-hermes.sh` (prompts answered "no").
- Session files installed (below); `greetd` enabled; default target `graphical`.
- Dev helpers on the `hermes` user's PATH: `hermes-os-build`, `hermes-os-sync`,
  `hermes-os-restart-shell`, `hermes-os-shot`.

## Session model (`linux/session/`)

| Piece | Role |
| --- | --- |
| `/etc/greetd/config.toml` | Logs `hermes` in on VT1 and runs `hermes-os-compositor`. Respawns when it exits. |
| `hermes-os-compositor` | Sets `XDG_*`, picks `WLR_RENDERER=pixman` when there is no GPU render node, sources `~/.config/hermes-os/session.env`, `exec cage -s -- hermes-os-session`. |
| `hermes-os-session` | Publishes `WAYLAND_DISPLAY` to systemd/D-Bus, starts PipeWire + portals, runs Electron with `HERMES_OS_KIOSK=1` on Wayland (Ozone). Restarts the shell on a crash (5 per minute), exits on a clean quit. |
| `hermes-os.desktop` | `wayland-sessions` entry so a normal greeter can also start Hermes OS. |

The Hermes backend is still spawned by the shell (`electron/backend/manager.ts`), the same as on
macOS. A systemd unit comes with the Stage 2 broker.

`~/.config/hermes-os/session.env` overrides (all optional; changes to this file or to the session
scripts need `sudo systemctl restart greetd`, because the running session loop keeps its old copy):

```
HERMES_OS_SCALE=1.5                          # page zoom for HiDPI framebuffers (1.5 for 2048x1280, 2 for 2880x1800)
HERMES_OS_DEV_SERVER=http://127.0.0.1:5180   # load the Vite dev server instead of dist/
HERMES_OS_REMOTE_DEBUG_PORT=9333             # Chrome DevTools protocol for scripted checks
HERMES_OS_NO_SANDBOX=1                       # if user namespaces are disabled
HERMES_OS_APP=/path/to/apps/os               # alternate build location
```

## Dev loop

- **From the Mac**: `bash linux/dev/push.sh` (rsync over SSH, build, restart shell,
  ~30 s). `bash linux/dev/push.sh ssh` opens a shell. `bash linux/dev/shot.sh` grabs a screenshot
  via `grim` into `linux/vm/build/shots/`.
- **Inside the VM** (UTM share): `hermes-os-sync`. Logs: `~/.local/state/hermes-os/shell.log`,
  `journalctl -u greetd`, `journalctl --user -b`.
- HMR: run `npm run dev:renderer` in an SSH session and set `HERMES_OS_DEV_SERVER` in
  `session.env`, then `hermes-os-restart-shell`.

Native modules must be installed on Linux, so the repo is copied (rsync) rather than used in place
from the share; `node_modules`, `dist`, `.git` and the upstream snapshot are excluded and fetched
inside the VM by `scripts/bootstrap.sh`.

## Known limits (Stage 1)

- `cage` is a kiosk compositor: a launched app (Firefox, Nautilus) covers the shell fullscreen and
  returns to it when closed. No window switching between foreign apps until the Stage 2 compositor.
- No calendar (`calendar.today` reports `unavailable`); Evolution Data Server integration is later.
- Display sleep (`system_control sleep_display`) is not available; lock uses `loginctl`.
- QEMU has no GPU acceleration on macOS: cage renders with pixman and Electron with
  `--disable-gpu`. UTM's Apple Virtualization backend gives virtio-gpu-gl.
- SELinux is permissive on the VM.
- Apple Silicon Macs cannot boot this natively (no Asahi support for M4/M5); the VM is the target.
  x86 hardware comes with the ISO work in the roadmap.
