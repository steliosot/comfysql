#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
cd "$REPO_ROOT"

SERVER="${1:-remote}"

STATUS_OUT="$(comfysql status "$SERVER")"
echo "$STATUS_OUT"
if [[ "$STATUS_OUT" != *"status=running_remote"* ]]; then
  echo "[sync_and_smoke_test] server is not reachable/running for alias '$SERVER'." >&2
  exit 3
fi

# Fail fast prechecks for required workflow/preset.
comfysql sql "$SERVER" --sql "DESCRIBE WORKFLOW txt2img_empty_latent;" >/dev/null
if ! comfysql sql "$SERVER" --sql "DESCRIBE PRESET default_run FOR txt2img_empty_latent;" >/dev/null; then
  echo "[sync_and_smoke_test] missing preset 'default_run' for table 'txt2img_empty_latent'." >&2
  exit 2
fi

comfysql sync "$SERVER"
comfysql sql "$SERVER" --compile-only --sql "EXPLAIN SELECT image FROM txt2img_empty_latent USING default_run WHERE prompt='post-sync smoke test' AND seed=505;"
