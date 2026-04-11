---
name: model_inventory_check
description: Query live server model inventory through ComfySQL models table for checkpoints, loras, and related assets.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧱","requires":{"bins":["comfysql"]}}}
---

# model_inventory_check

Use this skill before generation to verify model names available on the server.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).

## Execution

Run the SQL examples in:

- `{baseDir}/model_inventory_check.sql`

## Expected Output

- Sorted model name lists by category
- Fast validation target for checkpoint references

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
