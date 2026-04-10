---
name: cli_doctor
description: Run full connectivity diagnostics (health/object_info/models/websocket/auth) using comfy-agent doctor.
user-invocable: true
metadata: {"openclaw":{"emoji":"🩺","requires":{"bins":["comfy-agent"]}}}
---

# cli_doctor

Use this skill when status alone is not enough and you need detailed diagnostics for remote/server connectivity.

## Preconditions

- `comfy-agent` is installed.
- Server alias exists in config (for example `remote`).

## Execution

Run the command pack in:

- `{baseDir}/cli_doctor.sh`

## Coverage

- `health`
- `object_info`
- `models`
- `websocket`
- `auth_header`

## Expected Output

- Per-check lines: `doctor <check>=ok|fail detail=...`
- Final summary: `doctor_summary status=ok|fail failed_checks=N`

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
