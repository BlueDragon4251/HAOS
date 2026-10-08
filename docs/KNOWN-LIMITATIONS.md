# Known limitations

HAOS is development, not an accepted production distribution. The master prompt remains the complete target.

- Installed Fedora/ISO acceptance is incomplete; builds unsigned. Full SBOM/provenance, reproducible pins, Secure Boot/private updates unfinished.
- Inherited auto-login, observer wheel membership and initial password behavior do not meet production owner onboarding.
- Writable binds retain POSIX ownership/ACLs; general owner-approved ACL/idmapped access unfinished. Same-system-disk data is conservatively denied. LUKS unlocking is owner work; hotplug/remote filesystems unsupported.
- Shared host networking; egress and privileged loopback service protection incomplete. Inherited SELinux permissive configuration has no enforcing proof.
- Durable native missions exist; ordinary chat/voice/gateways are not unified with queue/trust identities.
- Complete upstream turn is not independent goal proof. Ambiguity blocks intentionally. Background cleanup, resumable downloads and parallel worktrees need further work.
- Native host GUI bridge access is withheld; safe broker, genuine capture and authenticated remote stream missing.
- Autonomous themes/skills lack accepted capability manifests, isolated generation/test, whole-theme atomic swap/watchdog/revocation.
- Provider/vault/local-model/budget provisioning unfinished. No provider-less probe proves a real model/Git mission.
- Task/event text may contain sensitive data; complete redaction/encryption/retention not guaranteed.
- Restic restore, broken-update rollback, GPU/resource measurements and long gateway missions remain outstanding.

See [evidence](HAOS.md) and [release gates](RELEASE.md). A green desktop suite or syntax-checked harness does not close these gaps.
