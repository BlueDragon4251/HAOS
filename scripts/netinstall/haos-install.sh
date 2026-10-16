#!/usr/bin/env bash
# Dual-channel HAOS network installer launcher for a Fedora Live environment.
set -Eeuo pipefail
umask 077
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_MANIFEST="${HAOS_RELEASE_MANIFEST:-https://raw.githubusercontent.com/BlueDragon4251/HAOS/main/releases/stable-image.txt}"
validate_image() {
  [[ "$1" =~ ^ghcr\.io/[a-z0-9_-]+(/[a-z0-9_.-]+)+@sha256:[0-9a-f]{64}$ ]] && [[ "$1" != *..* ]]
}
clear
echo "HERMES AUTONOMOUS OS — NETWORK INSTALLATION"
echo
echo "1) Install verified public stable release"
echo "2) Exit"
echo

if [[ "${1:-}" == "--stable" ]]; then selection=1
else read -r -p 'Selection [1]: ' selection
fi
case "${selection:-1}" in
  1)
    command -v curl >/dev/null || { echo "Missing curl" >&2; exit 1; }
    if ! getent ahostsv4 raw.githubusercontent.com >/dev/null 2>&1; then
      echo "No GitHub DNS resolution. Use F3 Network Settings; check DHCP/gateway/DNS." >&2
      exit 1
    fi
    # A stable reference must be published explicitly; never fall back to a private dev image.
    image="$(curl -fsSL --connect-timeout 15 --max-time 30 "$RELEASE_MANIFEST")"
    image="${image%$'\n'}"
    validate_image "$image" || { echo "No validated public release image manifest; installation aborted." >&2; exit 1; }
    echo "Stable release: $image"
    exec bash "$DIR/private-install.sh" --public "$image"
    ;;
  :dev)
    echo
    echo "Developer mode — private GitHub Container Registry"
    echo "A GitHub token with package read permission will be requested securely."
    exec bash "$DIR/private-install.sh" --select-dev
    ;;
  2) exit 0 ;;
  *) echo "Invalid selection" >&2; exit 1 ;;
esac
