# Gateways

Hermes messaging extras/adapters are installed without forking upstream. Adapter availability is not proof of authenticated durable ingress.

Current HAOS queue admission is the local peer-authenticated socket. Ordinary messaging sessions may run inside the same sandbox but do not automatically receive HAOS IDs, trust roles or owner rights.

Required work: platform/provider provisioning, sender/channel identity, roles/replay/admission limits and real authorized/unknown sender tests. No privileged HTTP policy endpoint or text-based root elevation is provided. Do not copy human browser/session credentials into service state.
