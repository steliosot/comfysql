---
name: asset_preflight_for_workflow
description: Preflight workflow image/audio assets by syncing local input/assets and running compile-only SQL checks.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧪","requires":{"bins":["comfy-agent"]}}}
---

# asset_preflight_for_workflow

Use this skill to prevent missing-asset failures before execution.

## Preconditions

- `comfy-agent` is installed.
- Relevant files exist in `input/assets`.

## Execution

Run the command pack in:

- `{baseDir}/asset_preflight_for_workflow.sh`

## Expected Output

- Asset copy preflight and upload summary
- Compile-only workflow validation passes

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
