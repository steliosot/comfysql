---
name: batch_sql_runner
description: Run one or more SQL files in batch mode with consistent server targeting and failure behavior.
user-invocable: true
metadata: {"openclaw":{"emoji":"🗂️","requires":{"bins":["comfysql","bash"]}}}
---

# batch_sql_runner

Use this skill to run SQL packs as reproducible batches.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- SQL files exist and are readable.

## Execution

Run the command pack in:

- `{baseDir}/batch_sql_runner.sh`

## Expected Output

- Per-file execution output
- Immediate stop on first failing SQL file

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
