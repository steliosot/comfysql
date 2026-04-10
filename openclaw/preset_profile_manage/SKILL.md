---
name: preset_profile_manage
description: Inspect and manage existing ComfySQL presets and profiles without creating new ones.
user-invocable: true
metadata: {"openclaw":{"emoji":"🎛️","requires":{"bins":["comfy-agent"]}}}
---

# preset_profile_manage

Use this skill for preset/profile inspection and cleanup workflows.

## Preconditions

- `comfy-agent` is installed.

## Execution

Run the SQL examples in:

- `{baseDir}/preset_profile_manage.sql`

## Notes

- This pack is intentionally no-create.
- It focuses on SHOW/DESCRIBE and optional DROP operations.

## Expected Output

- Lists of presets/profiles
- Detailed parameter inspection for selected entries

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
