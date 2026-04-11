---
name: workflow_validate_compile
description: Validate ComfySQL workflow execution plans safely using EXPLAIN and compile-only runs before submit.
user-invocable: true
metadata: {"openclaw":{"emoji":"✅","requires":{"bins":["comfysql"]}}}
---

# workflow_validate_compile

Use this skill to validate and inspect SQL workflow queries without generating output.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- Target workflow table already exists.

## Execution

Run the SQL examples in:

- `{baseDir}/workflow_validate_compile.sql`

Then run:

- `comfysql sql remote --compile-only --sql-file ${REPO_ROOT}/openclaw/workflow_validate_compile/workflow_validate_compile.sql`

## Expected Output

- `validated ...` summary
- API prompt compile output
- No submission lifecycle (`running/executed`) because compile-only mode is used

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
