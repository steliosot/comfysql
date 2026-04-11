---
name: sync_and_smoke_test
description: Refresh schema/model visibility with sync and verify readiness via a compile-only smoke query.
user-invocable: true
metadata: {"openclaw":{"emoji":"🔄","requires":{"bins":["comfysql","bash"]}}}
---

# sync_and_smoke_test

Use this skill after server updates or model changes to confirm readiness.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- At least one workflow table exists (for example `txt2img_empty_latent`).

## Execution

Run the command pack in:

- `{baseDir}/sync_and_smoke_test.sh`

## Expected Output

- Sync completes
- compile-only smoke query validates successfully

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
