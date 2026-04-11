---
name: relational_cleanup_migration
description: Safely migrate to relational CHARACTER/OBJECT aliases by pruning legacy bindings with backup, dry-run, and apply modes.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧹","requires":{"bins":["comfysql","python3","bash"]}}}
---

# relational_cleanup_migration

Use this skill to clean old per-workflow character bindings and keep a stable relational setup.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- Repo has `.state` files (`sql_asset_aliases.json`, `sql_workflow_slots.json`, `sql_character_bindings.json`).
- You know which aliases you want to keep (defaults are `char_bets,char_matt,obj_hat`).

## Execution

Run the command pack in:

- `{baseDir}/relational_cleanup_migration.sh`

## Modes

- Dry-run (default): preview only, no changes.
- Apply (`--apply`): create backup and write updated state files.

## Environment Overrides

- `KEEP_CHARACTERS` (default: `char_bets,char_matt`)
- `KEEP_OBJECTS` (default: `obj_hat`)

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
