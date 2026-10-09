# Agent local-network boundary

`haos-network.service` is a root oneshot with only `CAP_NET_ADMIN`; it installs the dedicated `inet haos_agent` nftables table before Hermes starts. Hermes binds its lifecycle to this required service. Missing nftables, an invalid identity/resolver configuration or a rejected transaction prevents startup. Stopping the helper does not remove the guard. Other host firewall tables are not flushed.

Rules apply only to the kernel socket UID of `haos-agent`, including sockets opened outside its user namespace. They reject the host's own addresses and private, loopback, link-local, shared-address, multicast and reserved destinations. Public Internet access is retained for providers; this is not a mission-specific destination allowlist or complete exfiltration policy.

Narrow exceptions permit TCP to the literal backend `127.0.0.1:9119`, DNS to the system stub and exact configured resolver addresses, and established **reply-direction** traffic from a server operated by the agent. Established original-direction connections do not bypass a new policy. DNS input must come from a root-owned, non-writable resolver file with protected original and resolved parent paths; addresses are numeric, validated and bounded. Arbitrary other ports on a DNS resolver are not permitted.

The nft transaction is checked before application and atomically reloads only the dedicated table. Resolver changes require an authenticated administrator to stop execution and reload the guard:

```sh
sudo haos-owner stop
# From a separately authenticated administrator/recovery console:
systemctl restart haos-network.service
sudo haos-owner start
```

The enrolled owner's restricted sudo grant has no arbitrary `systemctl` permission. An unattended NetworkManager/resolver reload broker remains missing. Changes to blocking lists similarly require rebuilding/reviewing image-owned code.

The disposable CI probe uses a new account, private nft table and real IPv4/IPv6 listeners. It checks denied loopback/mapped-address access, pre-existing connections after policy install/reload, actual backend replies, denied unprivileged rule removal and unaffected other-user traffic. Local unit tests validate rule generation, resolver trust, scope and failed validation; **the real kernel probe has not run** because GitHub account billing blocks new jobs before startup. Installed-guest receipts are also absent. Do not treat these policies as release-verified isolation.

AF_UNIX abstract sockets, enforcing SELinux coverage, per-mission public egress, DNS-channel exfiltration, remote filesystems, multi-user UID changes and complete owner-only local-service isolation require further implementation and acceptance.
