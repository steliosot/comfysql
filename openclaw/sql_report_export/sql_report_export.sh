#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
cd "$REPO_ROOT"

SERVER="${1:-remote}"
REPORT_PATH="${2:-${REPO_ROOT}/output/sql_report_export.md}"

STATUS_OUT="$(comfysql status "$SERVER")"
echo "$STATUS_OUT"
if [[ "$STATUS_OUT" != *"status=running_remote"* ]]; then
  echo "[sql_report_export] server is not reachable/running for alias '$SERVER'." >&2
  exit 3
fi

comfysql sql-report "$SERVER" \
  --download-output \
  --download-dir "${REPO_ROOT}/output" \
  --report "${REPORT_PATH}" \
  --title "SQL Run Report" \
  --sql "SELECT image FROM txt2img_empty_latent USING default_run PROFILE standard_50mm WHERE prompt='sql report export smoke test' AND seed=707 AND filename_prefix='sql_report_export_707';"
