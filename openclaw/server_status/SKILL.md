---
name: server_status
description: Check remote/server health quickly using comfysql status with alias-based targets.
user-invocable: true
metadata: {"openclaw":{"emoji":"🟢","requires":{"bins":["comfysql"]}}}
---

# server_status

Use this skill for a fast up/down connectivity check before running SQL or asset copy commands.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- Server alias exists in config (for example `remote`).

## Execution

Run the command pack in:

- `{baseDir}/server_status.sh`

## Expected Output

- `status=running_remote host=... port=...` or
- `status=stopped_remote host=... port=...`

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
