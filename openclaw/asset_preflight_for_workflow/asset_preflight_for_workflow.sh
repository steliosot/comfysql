#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
cd "$REPO_ROOT"

SERVER="${1:-remote}"

STATUS_OUT="$(comfy-agent status "$SERVER")"
echo "$STATUS_OUT"
if [[ "$STATUS_OUT" != *"status=running_remote"* ]]; then
  echo "[asset_preflight_for_workflow] server is not reachable/running for alias '$SERVER'." >&2
  exit 3
fi

# Fail fast prechecks for required workflow/preset.
comfy-agent sql "$SERVER" --sql "DESCRIBE WORKFLOW img2img_reference;" >/dev/null
if ! comfy-agent sql "$SERVER" --sql "DESCRIBE PRESET default_run FOR img2img_reference;" >/dev/null; then
  echo "[asset_preflight_for_workflow] missing preset 'default_run' for table 'img2img_reference'." >&2
  exit 2
fi

comfy-agent copy-assets "$SERVER" --all --dry-run
comfy-agent copy-assets "$SERVER" --all

comfy-agent sql "$SERVER" --compile-only --sql "EXPLAIN SELECT image FROM img2img_reference USING default_run WHERE input_image='bbk-euston.jpg' AND prompt='asset preflight check' AND seed=404;"
