---
name: relational_assets_setup
description: Register reusable CHARACTER/OBJECT aliases and bind workflow slots once for relational image reuse.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧬","requires":{"bins":["comfysql"]}}}
---

# relational_assets_setup

Use this skill to set up the new relational asset model end-to-end.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- Asset files already exist on server (run `copy-assets` first).
- Workflow tables already exist (for example `img2img_reference`, `img2img_2_inputs`).

## Execution

Run the SQL pack in:

- `{baseDir}/relational_assets_setup.sql`

## Coverage

- Create/update `CHARACTER` aliases
- Create/update `OBJECT` aliases
- Create/update per-workflow `SLOT` mappings
- Verify with `SHOW/DESCRIBE`

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
