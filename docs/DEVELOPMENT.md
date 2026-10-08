# Development

Work targets dev; imported main remains baseline pending review. Native desktop is apps/desktop; integration services are linux/haos. Preserve upstream authorship and avoid incompatible Hermes edits.

Use the commands in [testing](TESTING.md). Hermes updates change upstream/UPSTREAM.lock and require exact-snapshot checks of session.create, prompt.submit, session.interrupt, event epoch/sequence, questions and terminal receipts. Managed and standalone modes need separate verification.

Image packages/install/build-runtime scripts are image-builder operations, not personal-host provisioning commands. The guarded ISO harness uses fresh VM disk files only.

Owner operations remain outside the mission socket. New capabilities must not inherit root, observer home/environment or GUI bridge command authority. Verify negative operations as well as positive paths.
