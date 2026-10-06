#!/usr/bin/env bash
# Fetch the pinned upstream Hermes Agent snapshot into upstream/hermes-agent.
# Works without git (tarball by commit sha). Idempotent: skips when the sha already matches.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="$ROOT/upstream/UPSTREAM.lock"
DEST="$ROOT/upstream/hermes-agent"
STAMP="$DEST/.herald-os-upstream-sha"

repo="$(sed -n 's/^repo=//p' "$LOCK" | tr -d '[:space:]')"
sha="$(sed -n 's/^sha=//p' "$LOCK" | tr -d '[:space:]')"

if [[ -z "$repo" || -z "$sha" ]]; then
  echo "sync-upstream: UPSTREAM.lock must define repo= and sha=" >&2
  exit 1
fi

if [[ -f "$STAMP" && "$(cat "$STAMP")" == "$sha" ]]; then
  echo "sync-upstream: $repo@$sha already present"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "sync-upstream: fetching $repo@$sha"
# Retries ride out GitHub's rate limit (429), which many builds fetching at once can hit.
curl -fsSL --retry 6 --retry-delay 20 --retry-all-errors "https://github.com/$repo/archive/$sha.tar.gz" -o "$tmp/upstream.tar.gz"
mkdir -p "$tmp/extract"
tar -xzf "$tmp/upstream.tar.gz" -C "$tmp/extract" --strip-components=1

rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
mv "$tmp/extract" "$DEST"
echo "$sha" > "$STAMP"
echo "sync-upstream: done -> $DEST"
