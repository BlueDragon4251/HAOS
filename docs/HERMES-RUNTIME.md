# Hermes runtime

`haos-hermes.service` runs as `haos-agent` after first boot, networking and policy preparation. Source is pinned by `upstream/UPSTREAM.lock`. Image-only `build-runtime.sh` uses frozen upstream dependencies with web/messaging extras and Fedora's immutable `/usr/bin/python3.11`; RPM versions are recorded in `/usr/lib/haos/python-runtime.txt`.

The reviewed `linux/haos/runtime` overlay pins all runtime requirements with package hashes, including fixes for anyio, multidict, PyJWT, tornado and urllib3. Its preparation checks the exact upstream commit, original pyproject/uv.lock hashes and requirements digest before changing the conflicting PyJWT metadata. Installation requires hashes and `uv pip check`; installed versions and the source/requirements provenance remain in immutable `/usr/lib/haos/runtime-provenance`. Run `37818579514` verified the resolved dependencies with pip-audit, the actual pinned Hermes CLI and an expired-JWT regression. That CI result validates dependencies; the resulting updated Fedora image still requires its own build and guest evidence.

Writable home `/var/lib/haos-agent` appears as `/home/agent`; Hermes data is `/home/agent/.hermes`. `/var/lib/haos-workspace` appears as `/workspace`. Host homes, policy, raw devices, /sys and host sockets are not shared. Minimal passwd/group contains only the agent.

Backend is literal loopback `127.0.0.1:9119`. UI descriptor `/etc/haos/backend.json` points to the protected host token. Invalid managed configuration fails without unrestricted child fallback. Closing the UI does not stop the attached service.

The sandbox launcher passes the systemd credential through an inherited descriptor into a read-only file. The immutable sandbox-side launcher validates it and sets the backend environment before exec. The value is not included in Bubblewrap's public process arguments. The corresponding real kernel probe verifies file transfer and absence from process arguments; require a green result for the latest source commit.

Provider setup remains upstream configuration inside agent state. A validated HAOS credential wizard/vault is incomplete. Do not copy a human's credential/session directories. No provider-less probe is a real model mission. Bounded restarts do not prove unknown background work stopped; use [recovery](RECOVERY.md).
