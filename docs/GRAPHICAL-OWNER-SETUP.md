# HAOS initial graphical administrator setup — development

**Status:** native graphical setup source and hardened root-seat launcher are
in the development image, but the dedicated X11 VT8 seat is **disabled by
default** until its UEFI/BIOS input/graphics and firstboot/upgrade integration
are verified in QEMU and on hardware. This must not be reported as a finished
first-boot desktop. The existing tty2 owner recovery remains the fallback.

## Implemented, not yet hardware-verified
- A separate initial-setup authority in `haos.initial_setup`, callable only
  from root. There is **no Electron or Hermes direct RPC** into it.
- A native Tkinter UI (`haos.initial_setup_gui`) with German labels, a
  dark HAOS visual design, password-based separate owner enrollment and ten
  single-use recovery codes, system locale/keymap, single-provider configuration,
  GHCR read-only token entry and stable/dev bootc channel switching.
- One-time recovery codes remain visible until the operator confirms they
  have been saved off-device; if the setup crashes before acknowledgement,
  physical trusted setup must rotate them, invalidating previous codes.
- A private Xorg display only on VT8 (no TCP connections; random Xauthority
  cookie under /run); root X11 process launches no Electron and accepts no
  remote or observer connection.
- Existing installed owner accounts are never overwritten by this setup.
  The current provider UI supports **one active provider**. Multi-provider
  routing was separately implemented as a tested pure policy, not yet wired
  to the live model proxy; no false 'automatic' readiness.
- Gateways, remote desktop and Mobile device pairing require further work.

## Safety constraints and acceptance before enabling
- Graphical root enrollment and recovery are highly privileged. They must be
  isolated from ordinary observer/agent sessions and invoked only by the
  root-owned systemd service and physically trusted local display.
- Prove graphics and input on the target HP and disposable UEFI/BIOS QEMU.
- Prove the 20+ character password and offline recovery-code flow with PAM.
- Prove that root secret entry is not available to the observer, remote users,
  clipboard, Hermes, socket, logs, screenshots, or persistent home storage.
- Restore normal user session on completion with no root session remaining.
- Test migration (already-enrolled owners) without data/account deletion.
- Only then enable `haos-setup-desktop.service` for initial boot, and
  move the remaining owner CLI actions behind this trusted graphical UI.

Production installer must NOT silently switch to root if GUI setup fails.
