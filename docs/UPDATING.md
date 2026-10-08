# Updates

Fedora bootc architecture is retained. HAOS has no accepted private update registry, signer enrollment or tested rollback channel. Herald update URLs refer to upstream artifacts.

Review source updates on a branch, preserve credits, validate the independent Hermes pin, rebuild and test the exact ISO. Runtime dependencies are image-owned; skills/workspaces are untrusted writable state.

Before deployment require signing/provenance, persistent-store migrations, owner recovery, a deliberately broken-image rollback drill and backup restore. bootc command availability alone does not prove the complete HAOS update path.
