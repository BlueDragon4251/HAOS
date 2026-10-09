# Owner setup

HAOS creates a locked non-administrator observer account instead of Herald's empty-password wheel account. Initialization and a mandatory pre-session service remove inherited `wheel`/`sudo`/`admin` membership, lock empty passwords and install a validated UID-specific sudo denial, including inherited per-user NOPASSWD rules. Root/service/shared UIDs and privileged primary groups are rejected. The graphical session requires successful first-boot/security units; a security-unit failure blocks its start. Membership changes take effect in new sessions; old sessions must be terminated/rebooted before relying on revocation.

At `739bc62`, [CI run `37842665703`](https://github.com/BlueDragon4251/HAOS/actions/runs/37842665703) verified this against a real disposable account, first demonstrating inherited passwordless root execution and then verifying group removal, locked password, root-command and sudoedit denial. Installed-OS/session evidence is still required.

Automatic observer display remains enabled. A secure lock-screen and installer/recovery bootstrap flow are still missing. No default owner password or automatic owner privilege is created. Continue to use disposable VMs.

## Separate owner console enrollment

From an independently authenticated root console, stop execution, then create a new account:

```sh
haos-owner stop
haos-owner enroll your_owner_name
```

Passwords are entered twice through an interactive terminal, never as command arguments. Enrollment requires 20–256 characters, rejects control characters/account-name inclusion and requires the actual `pwscore` quality check. Missing tools or unverified quality fail closed. The account starts locked and must have an unshared non-system UID, no observer/service or administrator membership, and a verified installed password. Existing accounts are never repurposed.

The validated root-owned sudo rule denies other commands and permits only `/usr/bin/haos-owner` as root, with the owner's password required for every invocation, no reusable timestamp and no caller environment override. The launcher uses immutable `/usr/bin/python3 -I` so caller Python paths, startup hooks and the working directory cannot supply root code. Owner commands do not grant an arbitrary root shell. Account metadata and audit contain no password.

```sh
sudo haos-owner status
sudo haos-owner volume UUID:your-filesystem-uuid read-only
sudo haos-owner start
```

Provisioning failures remove the new sudo rule, lock the new account and revert any published owner registry record. The new home remains for root inspection; user data is never automatically deleted. A failed cleanup is an error requiring console recovery. Root-authored policies, external identities and later custom sudo includes can change authority and need separate review.

Local verification on 2026-10-09: 133 unit/regression tests, an actual hostile Python-startup/package denial, real `visudo` parsing and systemd/shell syntax passed. The additional disposable CI probe exercises actual PAM password installation, correct/incorrect sudo authentication, denied arbitrary commands/environment changes and absence of cached authentication. **It has not run:** GitHub account billing prevents new jobs from starting. Neither local tests nor this pending probe prove installer onboarding, a secure graphical lock screen, recovery codes or installed-OS authentication.

First boot adds the observer to haos-ui and generates per-host credentials, empty policy and managed attachment. haos-agent/haos-control are separate non-login accounts without wheel/sudo authority.

Current owner authority is authenticated root console/sudo. haos-owner requires effective UID 0 and stopped execution for policy/reconciliation. It writes atomically and audits under /var/lib/haos-owner. Model output/UI/gateway text never grants root.

The observer sudo denial is a managed final include in the distribution's standard sudoers layout. Root-authored custom policies or external identity/polkit grants require separate review; it is not a proof that every possible privilege mechanism is blocked. Owner wizard, installer bootstrap, recovery-code enrollment, provider/Git/gateway provisioning and mobile owner authorization remain incomplete.
