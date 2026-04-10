#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
cd "$REPO_ROOT"

SERVER="${1:-remote}"
SOURCE="${2:-}"

STATUS_OUT="$(comfy-agent status "$SERVER")"
echo "$STATUS_OUT"
if [[ "$STATUS_OUT" != *"status=running_remote"* ]]; then
  echo "[copy_assets] server is not reachable/running for alias '$SERVER'." >&2
  exit 3
fi

comfy-agent copy-assets "$SERVER" --all --dry-run
comfy-agent copy-assets "$SERVER" --all

if [[ -n "$SOURCE" ]]; then
  comfy-agent copy-assets "$SERVER" "$SOURCE"
fi
