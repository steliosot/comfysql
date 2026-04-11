#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
cd "$REPO_ROOT"

SERVER="${1:-remote}"
TIMEOUT="${2:-10}"

# Status-first gate before diagnostics.
comfysql status "$SERVER"
comfysql doctor "$SERVER" --timeout "$TIMEOUT"
