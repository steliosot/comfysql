#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
cd "$REPO_ROOT"

SERVER="${1:-remote}"
shift || true

if [[ "$#" -eq 0 ]]; then
  echo "Provide one or more .sql files." >&2
  exit 2
fi

STATUS_OUT="$(comfysql status "$SERVER")"
echo "$STATUS_OUT"
if [[ "$STATUS_OUT" != *"status=running_remote"* ]]; then
  echo "[batch_sql_runner] server is not reachable/running for alias '$SERVER'." >&2
  exit 3
fi

for SQL_FILE in "$@"; do
  echo "[batch_sql_runner] running: $SQL_FILE"
  comfysql sql "$SERVER" --sql-file "$SQL_FILE"
done
