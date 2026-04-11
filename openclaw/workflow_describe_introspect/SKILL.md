---
name: workflow_describe_introspect
description: Inspect workflow bindable fields and metadata using DESCRIBE WORKFLOW for safer query authoring.
user-invocable: true
metadata: {"openclaw":{"emoji":"🔎","requires":{"bins":["comfysql"]}}}
---

# workflow_describe_introspect

Use this skill to inspect table schema/bindable fields before writing WHERE bindings.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- Workflow table exists.

## Execution

Run the SQL examples in:

- `{baseDir}/workflow_describe_introspect.sql`

## Expected Output

- bindable/ambiguous fields per workflow
- workflow metadata and default params

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
