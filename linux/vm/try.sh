#!/usr/bin/env bash
# Try Herald OS on an Apple Silicon Mac in one command: fetch the ready-made VM disk from the latest
# release (or use one you have), and boot it with Apple's Virtualization framework (run-vf.sh). The
# first boot sets itself up (a few minutes, Hermes Agent included), then logs straight in.
#
#   bash linux/vm/try.sh                        # the latest release's disk
#   bash linux/vm/try.sh herald-os-<v>-aarch64.qcow2[.zst]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$HERE/build"
mkdir -p "$BUILD"

disk="${1:-}"
if [[ -z "$disk" ]]; then
  command -v gh >/dev/null || { echo "try.sh: needs the GitHub CLI (brew install gh) to fetch the release, or pass a disk" >&2; exit 1; }
  echo "==> Fetching the latest Herald OS VM disk"
  gh release download --repo iamlukethedev/Herald-OS --pattern 'herald-os-*-aarch64.qcow2.zst' --dir "$BUILD" --clobber
  disk="$(ls -t "$BUILD"/herald-os-*-aarch64.qcow2.zst | head -n 1)"
fi
if [[ "$disk" == *.zst ]]; then
  command -v zstd >/dev/null || { echo "try.sh: needs zstd to unpack the disk (brew install zstd)" >&2; exit 1; }
  out="$BUILD/$(basename "${disk%.zst}")"
  if [[ ! -f "$out" ]]; then
    echo "==> Unpacking $(basename "$disk")"
    zstd -d -q "$disk" -o "$out"
  fi
  disk="$out"
fi

exec bash "$HERE/run-vf.sh" --image "$disk"
