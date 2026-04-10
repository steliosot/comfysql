---
name: connectivity_triage
description: Triage remote connectivity quickly by chaining status and doctor checks in one diagnostic flow.
user-invocable: true
metadata: {"openclaw":{"emoji":"🌐","requires":{"bins":["comfy-agent","bash"]}}}
---

# connectivity_triage

Use this skill when commands fail and you need quick health diagnostics.

## Preconditions

- `comfy-agent` is installed.
- Server alias exists in config.

## Execution

Run the command pack in:

- `{baseDir}/connectivity_triage.sh`

## Expected Output

- `status=...`
- detailed `doctor` checks
- final diagnostic summary

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
