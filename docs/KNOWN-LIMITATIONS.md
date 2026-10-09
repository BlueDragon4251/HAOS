# Known limitations

HAOS is development, not an accepted production distribution. The master prompt remains the complete target.

- Installed Fedora/ISO acceptance is incomplete: image `9e0d4a3` really installed and booted, then failed backend health because the restrictive policy-service umask removed group directory traversal. This is corrected in source; actual dropped-UID and rebuilt-guest validation remains pending. Newer builds and actual build-time backend contracts passed; their install jobs were blocked before execution by GitHub account billing. Builds remain unsigned. Full SBOM/provenance, reproducible pins, Secure Boot/private updates unfinished.
- Writable binds retain POSIX ownership/ACLs; general owner-approved ACL/idmapped access unfinished. Same-system-disk data is conservatively denied. LUKS unlocking is owner work; hotplug/remote filesystems unsupported.
- Shared host networking now has a required socket-UID nftables guard for local/private destinations with narrow backend/DNS/reply exceptions. Local unit tests passed; real kernel and installed-guest probes have not run because GitHub jobs are blocked. AF_UNIX abstract sockets, resolver-change brokerage and complete egress/exfiltration policy remain incomplete. Inherited SELinux permissive configuration has no enforcing proof.
- Durable native missions exist; ordinary chat/voice/gateways are not unified with queue/trust identities.
- Complete upstream turn is not independent goal proof. Ambiguity blocks intentionally. Background cleanup, resumable downloads and parallel worktrees need further work.
- Native host GUI bridge access is withheld; safe broker, genuine capture and authenticated remote stream missing.
- Autonomous themes/skills lack accepted capability manifests, isolated generation/test, whole-theme atomic swap/watchdog/revocation.
- Provider/vault/local-model/budget provisioning unfinished. No provider-less probe proves a real model/Git mission.
- Task/event text may contain sensitive data; complete redaction/encryption/retention not guaranteed.
- Observer accounts now reject inherited administrator groups, empty passwords and sudo authority before session start. The real account/NOPASSWD/sudoedit probe passed at `739bc62` (run `37842665703`); the installed-guest check remains open. Separate root-console owner enrollment with password quality, per-invocation authenticated fixed CLI and rollback is implemented at `8f2957f`. Its actual PAM/sudo fixture is pending; local verification is not installed authentication proof. Installer/bootstrap, graphical locking, recovery codes, automatic observer display and review of all polkit/custom identity mechanisms remain open production gates.
- Owner-only local encrypted Restic snapshots and staged restore are implemented and passed a real deleted-project/incorrect-key runner probe at `88425fb` (run `37839452538`); installed-OS evidence remains a distinct open gate. External/off-host backup, retention/scheduling, whole-system restore, broken-update rollback, GPU/resource measurements and long gateway missions remain outstanding.

See [evidence](HAOS.md) and [release gates](RELEASE.md). A green desktop suite or syntax-checked harness does not close these gaps.
