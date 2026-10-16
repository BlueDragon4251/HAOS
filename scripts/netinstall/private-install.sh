#!/usr/bin/env bash
# HAOS private-registry installer. Run as root on a trusted Fedora LIVE system.
set -Eeuo pipefail
umask 077

die() { printf 'HAOS: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} == 0 ]] || die "Run as root"
for tool in podman lsblk findmnt readlink; do command -v "$tool" >/dev/null || die "Missing $tool"; done

PUBLIC=0
SELECT_DEV=0
if [[ "${1:-}" == "--public" ]]; then PUBLIC=1; shift; fi
if [[ "${1:-}" == "--select-dev" ]]; then SELECT_DEV=1; shift; fi
IMAGE="${1:-}"
if [[ "$SELECT_DEV" == 0 ]]; then
  [[ "$IMAGE" =~ ^ghcr\.io/[a-z0-9_-]+(/[a-z0-9_.-]+)+@sha256:[0-9a-f]{64}$ ]] ||
    die "Expected a GHCR digest-pinned image reference"
  [[ "$IMAGE" != *..* ]] || die "Invalid image reference"
fi

printf '\nHAOS NETWORK INSTALLER\n\n'
[[ "$SELECT_DEV" == 1 ]] || printf 'Image: %s\n' "$IMAGE"
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
printf '%s\n' '{}' > "$AUTHDIR/auth.json"
cleanup() { if [[ -n "${USB_MOUNT:-}" ]] && mountpoint -q "$USB_MOUNT"; then umount "$USB_MOUNT" || true; fi; rm -rf -- "$AUTHDIR"; }
trap cleanup EXIT
if [[ "$PUBLIC" == 0 ]]; then
read -r -p 'GitHub username: ' GHUSER
[[ "$GHUSER" =~ ^[A-Za-z0-9-]+$ ]] || die "Invalid GitHub username"
printf '\nDeveloper authentication:\n'
printf '1) USB token file (HAOS-DEV/token.txt)\n'
printf '2) HTTPS credential endpoint (also when booted via iVentoy PXE)\n'
printf '3) Paste token manually\n'
read -r -p 'Method [1]: ' AUTH_METHOD
case "${AUTH_METHOD:-1}" in
  1)
    command -v mount >/dev/null && command -v blkid >/dev/null || die "USB mount support missing"
    printf 'USB partitions:\n'
    lsblk -rpo NAME,TRAN,TYPE,SIZE | awk '$2 == "usb" || ($3 == "part" && $2 == "usb") {print}'
    read -r -p 'USB partition (e.g. /dev/sdb1): ' USB_PART
    USB_PART="$(readlink -f -- "$USB_PART")"
    [[ -b "$USB_PART" && "$(lsblk -dnro TYPE "$USB_PART")" == "part" ]] || die "Select a USB partition"
    USB_PARENT="$(lsblk -s -nro TRAN "$USB_PART" | grep -m1 -F usb || true)"
    [[ "$USB_PARENT" == usb ]] || die "Partition is not on a USB drive"
    USB_MOUNT="$AUTHDIR/usb"
    mkdir -m 700 "$USB_MOUNT"
    mount -o ro,nosuid,nodev,noexec "$USB_PART" "$USB_MOUNT" || die "Cannot mount USB read-only"
    USB_FILE="$USB_MOUNT/HAOS-DEV/token.txt"
    [[ -f "$USB_FILE" && ! -L "$USB_FILE" ]] || die "USB file HAOS-DEV/token.txt not found"
    IFS= read -r GHTOKEN < "$USB_FILE" || [[ -n "${GHTOKEN:-}" ]]
    umount "$USB_MOUNT"
    ;;
  2)
    command -v curl >/dev/null || die "Missing curl"
    echo 'Use a trusted HTTPS endpoint. iVentoy HTTP port 16000 must NOT host your token.'
    read -r -p 'HTTPS token URL: ' TOKEN_URL
    [[ "$TOKEN_URL" == https://* && "$TOKEN_URL" != *'@'* ]] || die "Only HTTPS URLs without embedded credentials are accepted"
    TOKEN_FILE="$AUTHDIR/token"
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
      --connect-timeout 10 --max-time 30 --max-filesize 8192 "$TOKEN_URL" -o "$TOKEN_FILE" || die "Token download failed"
    IFS= read -r GHTOKEN < "$TOKEN_FILE" || [[ -n "${GHTOKEN:-}" ]]
    rm -f -- "$TOKEN_FILE"
    unset TOKEN_URL
    ;;
  3)
    read -r -s -p 'Fine-grained/classic GHCR read token: ' GHTOKEN
    printf '\n'
    ;;
  *) die "Unsupported authentication method" ;;
esac
[[ -n "${GHTOKEN:-}" && "$GHTOKEN" != *[[:space:]]* && ${#GHTOKEN} -le 8192 ]] || die "Invalid or empty token"
printf '%s' "$GHTOKEN" | podman login --authfile "$AUTHDIR/auth.json" ghcr.io -u "$GHUSER" --password-stdin
unset GHTOKEN
fi
if [[ "$SELECT_DEV" == 1 ]]; then
  for tool in skopeo python3; do command -v "$tool" >/dev/null || die "Missing $tool for image picker"; done
  REPO="ghcr.io/bluedragon4251/haos"
  TAGS_FILE="$AUTHDIR/tags.json"
  skopeo list-tags --authfile "$AUTHDIR/auth.json" "docker://$REPO" > "$TAGS_FILE" ||
    die "Could not list private HAOS images; check package permission"
  mapfile -t DEV_TAGS < <(python3 - "$TAGS_FILE" <<'PY'
import json, re, sys
with open(sys.argv[1], encoding="utf-8") as source:
    tags = json.load(source).get("Tags", [])
for tag in sorted(set(tags), reverse=True):
    if re.fullmatch(r"dev-[0-9a-f]{12}", tag):
        print(tag)
PY
)
  (( ${#DEV_TAGS[@]} > 0 )) || die "No dev images available"
  echo
  echo "Available HAOS development images:"
  for i in "${!DEV_TAGS[@]}"; do printf '%2d) %s\n' "$((i+1))" "${DEV_TAGS[i]}"; done
  read -r -p "Select image number [1]: " CHOICE
  CHOICE="${CHOICE:-1}"
  [[ "$CHOICE" =~ ^[0-9]+$ ]] && (( CHOICE >= 1 && CHOICE <= ${#DEV_TAGS[@]} )) ||
    die "Invalid image number"
  TAG="${DEV_TAGS[CHOICE-1]}"
  INSPECT_FILE="$AUTHDIR/inspect.json"
  skopeo inspect --authfile "$AUTHDIR/auth.json" "docker://$REPO:$TAG" > "$INSPECT_FILE" ||
    die "Could not inspect selected image"
  DIGEST="$(python3 - "$INSPECT_FILE" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    print(json.load(source).get("Digest", ""))
PY
)"
  [[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Registry returned invalid image digest"
  IMAGE="$REPO@$DIGEST"
  printf '\nSelected: %s\nPinned image: %s\n' "$TAG" "$IMAGE"
fi
export REGISTRY_AUTH_FILE="$AUTHDIR/auth.json"
printf 'Fetching digest-pinned (not publisher-signed) image...\n'
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
  -v /run:/run \
  "$IMAGE" bootc install to-disk --wipe --skip-fetch-check "$DISK"
printf '\nHAOS installed to %s. Remove live media before reboot.\n' "$DISK"
printf 'IMPORTANT: private registry updates require separately configured read-only auth.\n'
