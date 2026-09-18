#!/usr/bin/env bash
# Migration: machines provisioned before the theme engine need theme.kdl and the default theme applied.
set -euo pipefail
command -v hermes-os-theme >/dev/null || exit 0
hermes-os-theme set "$(hermes-os-theme current)"
