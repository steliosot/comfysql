---
name: comfysql_query_ops
description: Discover and inspect ComfySQL state (workflows, presets, profiles, metadata, and model inventory) using read-only SQL commands.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧭","requires":{"bins":["comfy-agent"]}}}
---

# comfysql_query_ops

Use this skill for read-only ComfySQL discovery and diagnostics.

## Preconditions

- `comfy-agent` is installed.
- A server alias is configured (for example `remote`).

## Execution

Run the SQL examples in:

- `{baseDir}/comfysql_query_ops.sql`

## Coverage

- List available workflows/templates/presets/profiles
- Inspect workflow bindable fields
- Read workflow metadata (`intent`, `signature`, `meta`)
- Explain a query before execution
- Inspect server-side model inventory

## Output Contract

Return command output grouped by section:
- tables summary
- workflow detail
- preset/profile detail
- explain/validation detail
- models summary
