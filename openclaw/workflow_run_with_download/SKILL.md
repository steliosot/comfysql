---
name: workflow_run_with_download
description: Run ComfySQL SELECT workflows and download generated outputs locally in a single command flow.
user-invocable: true
metadata: {"openclaw":{"emoji":"📥","requires":{"bins":["comfysql"]}}}
---

# workflow_run_with_download

Use this skill when you want reproducible workflow runs with local output download.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- Target workflow table exists.

## Execution

Run the SQL examples in:

- `{baseDir}/workflow_run_with_download.sql`

Then run:

- `comfysql sql remote --sql-file ${REPO_ROOT}/openclaw/workflow_run_with_download/workflow_run_with_download.sql --download-output --download-dir ${REPO_ROOT}/output`

## Expected Output

- `validated ...`
- submit lifecycle (`submitted -> running -> executed`)
- downloaded output files under `output/`

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
