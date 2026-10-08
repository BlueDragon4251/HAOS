# Owner setup

HAOS creates a locked non-administrator observer account instead of Herald's empty-password wheel account. Initialization and a mandatory pre-session service remove inherited `wheel`/`sudo`/`admin` membership, lock empty passwords and install a validated UID-specific sudo denial, including inherited per-user NOPASSWD rules. Root/service/shared UIDs and privileged primary groups are rejected. The graphical session requires successful first-boot/security units; a security-unit failure blocks its start. Membership changes take effect in new sessions; old sessions must be terminated/rebooted before relying on revocation.

At `739bc62`, [CI run `37842665703`](https://github.com/BlueDragon4251/HAOS/actions/runs/37842665703) verified this against a real disposable account, first demonstrating inherited passwordless root execution and then verifying group removal, locked password, root-command and sudoedit denial. Installed-OS/session evidence is still required.

Automatic observer display remains enabled. It is not authenticated owner enrollment or a secure lock-screen flow. No default owner password or automatic owner privilege is created; an independently authenticated administrator/recovery console is required for owner operations. Owner enrollment, strong authentication and recovery access still need to be completed and proven before release. Continue to use disposable VMs.

First boot adds the observer to haos-ui and generates per-host credentials, empty policy and managed attachment. haos-agent/haos-control are separate non-login accounts without wheel/sudo authority.

Current owner authority is authenticated root console/sudo. haos-owner requires effective UID 0 and stopped execution for policy/reconciliation. It writes atomically and audits under /var/lib/haos-owner. Model output/UI/gateway text never grants root.

The sudo denial is a managed final include in the distribution's standard sudoers layout. Root-authored custom policies or external identity/polkit grants require separate review; it is not a proof that every possible privilege mechanism is blocked. Owner wizard, strong-auth/recovery-code enrollment, provider/Git/gateway provisioning and mobile owner authorization remain incomplete.
