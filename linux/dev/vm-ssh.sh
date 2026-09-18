#!/usr/bin/env bash
# Run a command in the Hermes OS VM (or open a shell). Finds the VM whichever runner started it:
# vfkit (NAT address) or QEMU (127.0.0.1:2222). Override with HERMES_VM_HOST / HERMES_VM_PORT.
#
#   bash linux/dev/vm-ssh.sh                      # interactive shell
#   bash linux/dev/vm-ssh.sh 'systemctl is-active greetd'
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$HERE/../vm/build"
KEY="$BUILD/id_hermes"

HOST="${HERMES_VM_HOST:-}"
PORT="${HERMES_VM_PORT:-}"

if [[ -z "$HOST" ]]; then
  if [[ -f "$BUILD/vfkit.pid" ]] && kill -0 "$(cat "$BUILD/vfkit.pid")" 2>/dev/null; then
    HOST="$(bash "$HERE/../vm/run-vf.sh" ip || true)"
    PORT="${PORT:-22}"
  fi
fi
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-2222}"

exec ssh -i "$KEY" -p "$PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=6 hermes@"$HOST" "$@"
