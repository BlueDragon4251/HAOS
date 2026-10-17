#!/usr/bin/env bash
# Dedicated physical rescue TTY with no GUI dependency.
set -Eeuo pipefail
while true; do
  printf '\033[2J\033[H'
  printf 'HAOS TEXT INSTALLER - TTY2\n'
  printf 'You can return to the GUI with Ctrl+Alt+F1.\n\n'
  /usr/bin/bash /usr/local/sbin/haos-install.sh || true
  printf '\nPress ENTER to return to the menu.\n'
  read -r _ || true
done
