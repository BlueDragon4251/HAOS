# Owner setup

The development image inherits Herald's observer account/first-login configuration. Auto-login, observer wheel membership and initial password behavior are not an accepted production owner onboarding flow. Use disposable VMs until independent owner authentication, locking and recovery enrollment are implemented/tested.

First boot adds the observer to haos-ui and generates per-host credentials, empty policy and managed attachment. haos-agent/haos-control are separate non-login accounts without wheel/sudo authority.

Current owner authority is authenticated root console/sudo. haos-owner requires effective UID 0 and stopped execution for policy/reconciliation. It writes atomically and audits under /var/lib/haos-owner. Model output/UI/gateway text never grants root.

Owner wizard, strong-auth/recovery-code enrollment, provider/Git/gateway provisioning and mobile owner authorization remain incomplete.
