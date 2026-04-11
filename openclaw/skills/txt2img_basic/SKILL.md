---
name: txt2img_basic
description: Generate one image from the txt2img_empty_latent workflow table using ComfySQL with preset/profile and prompt+seed overrides.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧱","requires":{"bins":["comfysql"]}}}
---

# txt2img_basic

Use this skill when an agent needs one reliable text-to-image run via `comfysql sql remote`.

## Preconditions

- `comfysql` is installed in the active environment (`comfy-agent` compatibility alias is also supported).
- Comfy server can be started by `comfysql`.
- SQL table `txt2img_empty_latent` exists:
  - `CREATE TABLE txt2img_empty_latent AS WORKFLOW '${REPO_ROOT}/input/workflows/txt2img_empty_latent.json';`
- Recommended preset/profile exist:
  - `default_run`
  - `standard_50mm`

## Inputs

Required:
- `prompt` (string)
- `seed` (integer)

Optional:
- `preset` (string, default: `default_run`)
- `profile` (string, default: `standard_50mm`)
- `negative_prompt` (string)
- `steps` (integer)
- `cfg` (float)
- `width` (integer)
- `height` (integer)
- `filename_prefix` (string)
- `compile_only` (boolean, default: `false`)

## Execution

### Path A: preset + profile (recommended)

```bash
comfysql sql remote --sql "SELECT image FROM txt2img_empty_latent USING ${preset} PROFILE ${profile} WHERE prompt='${prompt}' AND seed=${seed};"
```

Dry-run validation (compile only):

```bash
comfysql sql remote --compile-only --sql "SELECT image FROM txt2img_empty_latent USING ${preset} PROFILE ${profile} WHERE prompt='${prompt}' AND seed=${seed};"
```

## Output Contract

On success, capture and return:
- `status`: `success`
- `table`: `txt2img_empty_latent`
- `prompt`
- `seed`
- `preset` (if used)
- `profile` (if used)
- `api_prompt_path` (from CLI output)
- `output_files` (paths discovered under Comfy output folder after run)

On failure, return:
- `status`: `error`
- `error_type`: one of `sql_parse`, `validation_failed`, `submit_failed`, `runtime`
- `error_message` (exact CLI message)
- `suggested_fix` (short actionable hint)

## Error Handling

- If preset/profile is missing, run:
  - `comfysql sql remote --sql "SHOW PRESETS;"`
  - `comfysql sql remote --sql "SHOW PROFILES;"`
- If table is missing, create it with `CREATE TABLE ... AS WORKFLOW` and retry.

## Recommended Agent Policy

1. Run compile-only first for safety on first attempt.
2. If compile-only passes, run submit.
3. Prefer changing only `prompt` and `seed` across iterative generations to maximize cache reuse.
4. Do not restart server between attempts.

## Example Invocation

```bash
comfysql sql remote --sql "SELECT image FROM txt2img_empty_latent USING default_run PROFILE standard_50mm WHERE prompt='a cinematic portrait of a woman' AND seed=12345;"
```
