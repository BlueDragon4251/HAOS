#!/usr/bin/env bash
# From the Mac: push this repo into the VM over SSH, build it there, restart the shell.
# Works with the QEMU runner (linux/vm/run-qemu.sh) and with UTM (forward guest port 22 to 2222,
# or set HERMES_VM_HOST to the VM's IP).
#
#   bash linux/dev/push.sh                      # sync + build + restart
#   bash linux/dev/push.sh --with-hermes-config # also copy ~/.hermes/{config.yaml,.env,auth.json}
#   bash linux/dev/push.sh --no-build           # sync only
#   bash linux/dev/push.sh ssh                  # open a shell in the VM
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
KEY="$ROOT/linux/vm/build/id_hermes"
HOST="${HERMES_VM_HOST:-127.0.0.1}"
PORT="${HERMES_VM_PORT:-2222}"
SSH=(ssh -i "$KEY" -p "$PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR hermes@"$HOST")

[[ -f "$KEY" ]] || { echo "missing $KEY: run bash linux/vm/make-seed.sh first" >&2; exit 1; }

BUILD=1
WITH_CONFIG=
for arg in "$@"; do
  case "$arg" in
    ssh) exec "${SSH[@]}" ;;
    --no-build) BUILD= ;;
    --with-hermes-config) WITH_CONFIG=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

echo "==> waiting for sshd on $HOST:$PORT"
for _ in $(seq 1 60); do
  "${SSH[@]}" -o ConnectTimeout=3 true 2>/dev/null && break
  sleep 3
done
"${SSH[@]}" -o ConnectTimeout=3 true

echo "==> syncing repo -> hermes@$HOST:~/Hermes-OS"
"${SSH[@]}" 'mkdir -p ~/Hermes-OS'
rsync -az --delete \
  --exclude node_modules --exclude dist --exclude release --exclude .git \
  --exclude 'upstream/hermes-agent' --exclude 'linux/vm/build' --exclude '.DS_Store' \
  -e "ssh -i $KEY -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR" \
  "$ROOT/" hermes@"$HOST":Hermes-OS/

if [[ -n "$WITH_CONFIG" ]]; then
  echo "==> copying Hermes config (model/provider credentials) into the VM"
  "${SSH[@]}" 'mkdir -p ~/.hermes && chmod 700 ~/.hermes'
  for f in config.yaml .env auth.json; do
    if [[ -f "$HOME/.hermes/$f" ]]; then
      scp -q -i "$KEY" -P "$PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "$HOME/.hermes/$f" hermes@"$HOST":.hermes/"$f"
    fi
  done
fi

if [[ -n "$BUILD" ]]; then
  "${SSH[@]}" 'export PATH="$HOME/.local/bin:$PATH"; bash ~/Hermes-OS/linux/dev/build.sh && bash ~/Hermes-OS/linux/dev/restart-shell.sh'
fi
echo "==> done"
