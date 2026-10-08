# Threat model

Treat prompts/model output, gateways, generated skills, cloned code and web content as untrusted. Arbitrary agent code must be constrained by enforcement, not prompt rules.

| Boundary | Control | Remaining exposure |
| --- | --- | --- |
| Agent/host data | Mandatory namespace, explicit binds, hidden devices, no capabilities | Kernel/launcher exploits, enforcing LSM unverified |
| Agent/owner | Protected policy/root mounts, no owner endpoint | Root can change policy; owner onboarding incomplete |
| UI/controller | Fixed socket/methods, kernel peer UID | Authorized observer can submit work; roles incomplete |
| Agent/GUI | Host-command bridge not exposed | Safe GUI broker/capture missing |
| Network | Authenticated literal-loopback backend | Shared host network; egress/other loopback services |
| Crash/replay | Durable marker/receipts, retained uncertain lock | External effects need owner inspection |
| Secrets | Host credential and separate state identities | Provider key access needed; redaction/encryption/retention incomplete |

Independent root/firmware compromise exceeds an unprivileged namespace's protection. Read/write data grants permit destructive file operations within scope, never partitioning/LUKS-key/policy changes.

Ubuntu kernel probes prove specific operations, not Fedora boot or the entire attack surface. Actual installed QEMU receipts and further adversarial acceptance are required.
