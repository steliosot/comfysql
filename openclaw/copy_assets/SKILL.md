---
name: copy_assets
description: Copy local input assets to a configured Comfy remote/server via comfy-agent copy-assets with dry-run and apply modes.
user-invocable: true
metadata: {"openclaw":{"emoji":"📦","requires":{"bins":["comfy-agent"]}}}
---

# copy_assets

Use this skill to sync local files from `input/assets` (or a specific file/folder) to the Comfy server input path.

## Preconditions

- `comfy-agent` is installed.
- Server alias exists in config (for example `remote`).
- Local assets exist under `${REPO_ROOT}/input/assets`.

## Execution

Run the command pack in:

- `{baseDir}/copy_assets.sh`

## Coverage

- Dry-run listing (`--dry-run`) before upload.
- Bulk copy (`--all`) for `input/assets`.
- Optional single-source copy (`copy-assets <server> <source>`).

## Expected Output

- `copy_assets ... files=N dry_run=...`
- `copy_assets_done uploaded=... skipped_existing=... failed=...`
- If failures happen, `copy_failed ... error=...` lines.

## Output Contract

On success, return:

- `status`: `success`
- `errors`: `[]`
- `artifacts`: list of relevant files/ids/summary rows produced by the run
- `next_step`: one concrete recommended next action

On failure, return:

- `status`: `error`
- `errors`: non-empty list of actionable error messages
- `artifacts`: any partial outputs generated before failure
- `next_step`: one concrete fix command to retry safely
