# Hermes runtime

`haos-hermes.service` runs as `haos-agent` after first boot, networking and policy preparation. Source is pinned by `upstream/UPSTREAM.lock`. Image-only `build-runtime.sh` uses frozen upstream dependencies with web/messaging extras and Fedora's immutable `/usr/bin/python3.11`; RPM versions are recorded in `/usr/lib/haos/python-runtime.txt`.

Writable home `/var/lib/haos-agent` appears as `/home/agent`; Hermes data is `/home/agent/.hermes`. `/var/lib/haos-workspace` appears as `/workspace`. Host homes, policy, raw devices, /sys and host sockets are not shared. Minimal passwd/group contains only the agent.

Backend is literal loopback `127.0.0.1:9119`. UI descriptor `/etc/haos/backend.json` points to the protected host token. Invalid managed configuration fails without unrestricted child fallback. Closing the UI does not stop the attached service.

Provider setup remains upstream configuration inside agent state. A validated HAOS credential wizard/vault is incomplete. Do not copy a human's credential/session directories. No provider-less probe is a real model mission. Bounded restarts do not prove unknown background work stopped; use [recovery](RECOVERY.md).
