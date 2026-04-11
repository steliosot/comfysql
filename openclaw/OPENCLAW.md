# OpenClaw Skills

This folder contains reusable skills/packs for common ComfySQL tasks run with `comfysql`.

Compatibility alias: `comfy-agent` is still supported.

Each skill has:

- `SKILL.md` (what it does)
- `.sql` or `.sh` pack (commands to run)

## Skill List

- `asset_preflight_for_workflow`  
  Preflight assets: copy local assets and run compile-only checks before execution.

- `batch_sql_runner`  
  Run multiple SQL files in batch mode with fail-fast behavior.

- `cli_doctor`  
  Run full diagnostics (`health`, `object_info`, `models`, websocket, auth).

- `comfysql_query_ops`  
  Read-only SQL discovery: tables, workflows, presets/profiles, metadata, models.

- `connectivity_triage`  
  Quick connectivity debugging flow using `status` + `doctor`.

- `copy_assets`  
  Upload assets from `input/assets` (dry-run and apply modes).

- `img2img_2_inputs`  
  Run two-image reference img2img workflow examples.

- `img2img_reference`  
  Run single-reference img2img workflow examples.

- `model_inventory_check`  
  Query live model inventory from ComfySQL `models`.

- `preset_profile_manage`  
  Inspect and manage presets/profiles (show/describe/drop flows).

- `relational_cleanup_migration`  
  Safely prune legacy character bindings and keep relational aliases/slots with backup support.

- `server_status`  
  Fast server up/down check.

- `sql_report_export`  
  Run one SQL statement and export a Markdown report with embedded images.

- `sync_and_smoke_test`  
  Run sync plus compile-only smoke checks.

- `txt2img_empty_latent`  
  Run txt2img workflow examples with preset/profile combinations.

- `txt2img_basic`  
  Minimal one-shot txt2img run contract for agent/tool orchestration.

- `relational_assets_setup`  
  Create/reuse CHARACTER and OBJECT aliases and bind workflow slots once.

- `workflow_describe_introspect`  
  Inspect bindable workflow fields and metadata before writing queries.

- `workflow_run_with_download`  
  Execute workflow SQL and download generated outputs in one flow.

- `workflow_validate_compile`  
  Validate execution plans with `EXPLAIN` / `--compile-only` before submit.

## How To Use

1. Pick a skill folder.
2. Read its `SKILL.md`.
3. Run the provided `.sql` or `.sh` pack.
