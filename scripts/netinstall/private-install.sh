#!/usr/bin/env bash
# HAOS private-registry installer. Run as root on a trusted Fedora LIVE system.
set -Eeuo pipefail
umask 077

die() { printf 'HAOS: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} == 0 ]] || die "Run as root"
for tool in podman lsblk findmnt readlink; do command -v "$tool" >/dev/null || die "Missing $tool"; done

PUBLIC=0
if [[ "${1:-}" == "--public" ]]; then PUBLIC=1; shift; fi
IMAGE="${1:-}"
[[ "$IMAGE" =~ ^ghcr\.io/[a-z0-9_-]+(/[a-z0-9_.-]+)+@sha256:[0-9a-f]{64}$ ]] ||
  die "Usage: sudo bash private-install.sh ghcr.io/owner/haos@sha256:<64 lowercase hex>"
[[ "$IMAGE" != *..* ]] || die "Invalid image reference"

printf '\nHAOS PRIVATE REGISTRY INSTALLER\nImage: %s\n\n' "$IMAGE"
printf 'Physical block devices:\n'
lsblk -dpno NAME,SIZE,MODEL,TYPE,TRAN | awk '$4 == "disk" {print}'
read -r -p 'Target entire disk (e.g. /dev/nvme0n1): ' DISK
[[ "$DISK" == /dev/* && ! "$DISK" =~ [[:space:]] ]] || die "Invalid device"
DISK="$(readlink -f -- "$DISK")"
[[ -b "$DISK" && "$(lsblk -dnro TYPE "$DISK")" == disk ]] || die "Not a physical whole disk"
# Refuse any disk with mounted partitions, including the live media.
while IFS= read -r node; do
  if findmnt -rn -S "$node" >/dev/null; then die "Mounted device $node belongs to target disk"; fi
done < <(lsblk -nrpo NAME "$DISK")
printf '\nDANGER: ALL DATA ON %s WILL BE PERMANENTLY DESTROYED.\n' "$DISK"
read -r -p "Type exact disk path to confirm: " CONFIRM
[[ "$CONFIRM" == "$DISK" ]] || die "Confirmation failed"

AUTHDIR="$(mktemp -d /run/haos-ghcr-auth.XXXXXXXX)"
chmod 700 "$AUTHDIR"
printf '{}\\n' > "$AUTHDIR/auth.json"
cleanup() { podman logout --authfile "$AUTHDIR/auth.json" ghcr.io >/dev/null 2>&1 || :; rm -rf -- "$AUTHDIR"; }
trap cleanup EXIT
if [[ "$PUBLIC" == 0 ]]; then
read -r -p 'GitHub username: ' GHUSER
[[ "$GHUSER" =~ ^[A-Za-z0-9-]+$ ]] || die "Invalid GitHub username"
read -r -s -p 'Fine-grained/classic GHCR read token: ' GHTOKEN
printf '\n'
[[ -n "$GHTOKEN" ]] || die "Empty token"
printf '%s' "$GHTOKEN" | podman login --authfile "$AUTHDIR/auth.json" ghcr.io -u "$GHUSER" --password-stdin
unset GHTOKEN
fi
export REGISTRY_AUTH_FILE="$AUTHDIR/auth.json"
printf 'Fetching exact signed-by-digest (not cryptographically publisher-signed) image...\n'
podman pull --authfile "$REGISTRY_AUTH_FILE" "$IMAGE"
read -r -p 'Type WIPE to begin permanent installation: ' CONFIRM_WIPE
[[ "$CONFIRM_WIPE" == WIPE ]] || die "Cancelled"
# bootc runs from the TARGET image, with the host disk exposed.
# Private update checks cannot pass without persisted registry credentials:
# explicitly skip the day-2 fetch check. No credentials are baked into the OS.
podman run --rm --privileged --pid=host --ipc=host \
  --security-opt label=disable \
  -v /var/lib/containers:/var/lib/containers \
  -v /dev:/dev \
  "$IMAGE" bootc install to-disk --wipe --skip-fetch-check "$DISK"
printf '\nHAOS installed to %s. Remove live media before reboot.\n' "$DISK"
printf 'IMPORTANT: private registry updates require separately configured read-only auth.\n'
