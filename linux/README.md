# linux/

Everything needed to run Herald OS as the whole desktop of a Fedora machine (Stage 1: a VM on
your Mac). Full guide: [docs/LINUX.md](../docs/LINUX.md).

```
linux/
  provision.sh            first-boot provisioner (root, idempotent)
  session/                greetd config, compositor + session launchers, wayland-sessions entry
  dev/                    push.sh (Mac -> VM), build.sh / sync.sh / restart-shell.sh / shot.sh (VM)
  vm/                     download-image.sh, make-seed.sh (cloud-init), run-qemu.sh
  vm/build/               generated: image, seed ISO, SSH key, overlay disk, screenshots (gitignored)
```

```bash
bash linux/vm/download-image.sh && bash linux/vm/make-seed.sh && bash linux/vm/run-qemu.sh
bash linux/vm/run-qemu.sh console            # first boot provisions for several minutes
bash linux/dev/push.sh --with-hermes-config  # build the shell in the VM, copy model config (not OAuth logins)
bash linux/dev/push.sh ssh                   # then: hermes login
```
