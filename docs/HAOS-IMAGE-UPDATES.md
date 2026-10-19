# HAOS live image update channels (development preview)

HAOS is installed from a digest-pinned image, which is reproducible but never
sees later dev image tags. On the development branch, the GHCR pipeline now
publishes both immutable `dev-<commit>` and moving `dev-current` tags. Public
stable is **not** automatically published.

## Owner-only setup

First enroll an independent owner at Ctrl+Alt+F2 (required by HAOS), then return
to the desktop (Ctrl+Alt+F1). In the Terminal, authenticate with `su - OWNER`.
As that owner:

```sh
sudo haos-owner update login
sudo haos-owner update channel dev --auto-stage
sudo haos-owner update status
```

The login prompts for GitHub username and a **read-only** `read:packages` PAT.
It writes a persistent root-private `/etc/ostree/auth.json`; it never puts the
token in the container image, git, debug logs, browser local storage or the
observer's home directory. This is not a generic sudo/root escalation for the
desktop. Keep the token protected; root on the machine can still access it.
Revoking the PAT on GitHub invalidates it. `sudo haos-owner update logout`
removes the local credential. Until enrollment, the image cannot update itself
from private GHCR; the ephemeral ISO installation login is deliberately erased.

The `bootc switch` command changes which *tag* future updates track. It also
stages that image for the next reboot; verify the source before making changes.
The root timer checks every six hours, staging newer images only when the owner
opted into `--auto-stage`. It **never automatically reboots** the computer.
An older deployment is available for bootc rollback, but this feature is not
a proven end-to-end tested recovery mechanism yet.

To manually check or stage after login:

```sh
sudo haos-owner update check
sudo haos-owner update stage
```

For future official public releases: `sudo haos-owner update channel stable`.
Do not use it before the `ghcr.io/bluedragon4251/haos:stable` tag is officially
published; the command fails without changing the configured channel.

### UI limitations and installed machines

Settings > About shows only the sanitized status published by the root timer.
The graphical observer **cannot** enter or store owner/GHCR secrets; moving that
operation into Settings requires an independently authenticated owner broker,
which has not been built. Current managed Hermes provider configuration likewise
requires `sudo haos-owner provider configure` under the authenticated owner.
The setup/provider form builds only owner instructions; it does not claim to
configure Hermes.

The first installation already on a laptop contains its own immutable code.
A new GitHub commit or ISO **does not** patch that booted version automatically.
An initial trusted update/reinstall is required to introduce this update
component; do not try unreviewed root scripts in the observer session.
