---
name: sql_report_export
description: Run one SQL statement and export a Markdown run report with SQL, metadata, and embedded output images.
user-invocable: true
metadata: {"openclaw":{"emoji":"📝","requires":{"bins":["comfysql","bash"]}}}
---

# sql_report_export

Use this skill to generate reproducible run reports for demos, QA, and sharing.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- Target workflow/preset/profile exist.

## Execution

Run the command pack in:

- `{baseDir}/sql_report_export.sh`

## Coverage

- Executes one SQL statement
- Downloads outputs
- Writes markdown report file

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
