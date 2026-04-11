#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
cd "$REPO_ROOT"

SERVER="${1:-remote}"
WORKFLOW="${2:-img2img_reference}"
PRESET="${3:-default_run}"
INPUT_IMAGE="${4:-bbk-euston.jpg}"

STATUS_OUT="$(comfysql status "$SERVER")"
echo "$STATUS_OUT"
if [[ "$STATUS_OUT" != *"status=running_remote"* ]]; then
  echo "[asset_preflight_for_workflow] server is not reachable/running for alias '$SERVER'." >&2
  exit 3
fi

# Fail fast prechecks for required workflow/preset.
comfysql sql "$SERVER" --sql "DESCRIBE WORKFLOW ${WORKFLOW}" >/dev/null
if ! comfysql sql "$SERVER" --sql "DESCRIBE PRESET ${PRESET} FOR ${WORKFLOW}" >/dev/null; then
  echo "[asset_preflight_for_workflow] missing preset '${PRESET}' for table '${WORKFLOW}'." >&2
  exit 2
fi

comfysql copy-assets "$SERVER" --all --dry-run
comfysql copy-assets "$SERVER" --all

comfysql sql "$SERVER" --compile-only --sql "EXPLAIN SELECT image FROM ${WORKFLOW} USING ${PRESET} WHERE input_image='${INPUT_IMAGE}' AND prompt='asset preflight check' AND seed=404"
