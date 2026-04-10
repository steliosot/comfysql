---
name: txt2img_basic
description: Generate one image from the txt2img_empty workflow table using ComfySQL with optional preset/profile and explicit prompt+seed overrides.
user-invocable: true
---

# txt2img_basic

Use this skill when an agent needs a single-step text-to-image generation via `comfy-agent sql`.
This skill is designed for tool orchestration systems (for example OpenClaw) that need a predictable command contract and deterministic outputs.

## Preconditions

- `comfy-agent` is installed in the active environment.
- Comfy server can be started by `comfy-agent`.
- SQL table `txt2img_empty` exists:
  - `CREATE TABLE txt2img_empty AS WORKFLOW '/absolute/path/to/s_txt2img_empty_latent.json';`
- A valid checkpoint exists in Comfy models (example: `juggernaut_reborn.safetensors`).

## Inputs

Required:
- `prompt` (string)
- `seed` (integer)

Optional:
- `preset` (string, default: `zehra_1`)
- `profile` (string, default: `cinematic_portrait`)
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
comfy-agent sql --sql "SELECT image FROM txt2img_empty USING ${preset} PROFILE ${profile} WHERE prompt='${prompt}' AND seed=${seed};"
```

### Path B: explicit overrides (no preset/profile)

```bash
comfy-agent sql --sql "SELECT image FROM txt2img_empty WHERE ckpt_name='juggernaut_reborn.safetensors' AND prompt='${prompt}' AND seed=${seed};"
```

### Dry-run validation (compile only)

```bash
comfy-agent sql --compile-only --sql "SELECT image FROM txt2img_empty USING ${preset} PROFILE ${profile} WHERE prompt='${prompt}' AND seed=${seed};"
```

## Output Contract

On success, capture and return:
- `status`: `success`
- `table`: `txt2img_empty`
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

- If prompt submit fails with model validation (`ckpt_name` not allowed), retry with a valid checkpoint name from server validation output.
- If preset/profile is missing, run:
  - `comfy-agent sql --sql "SHOW PRESETS;"`
  - `comfy-agent sql --sql "SHOW PROFILES;"`
- If table is missing, create it with `CREATE TABLE ... AS WORKFLOW` and retry.

## Recommended Agent Policy

1. Run compile-only first for safety on first attempt.
2. If compile-only passes, run submit.
3. Prefer changing only `prompt` and `seed` across iterative generations to maximize cache reuse.
4. Do not restart server between attempts.

## Example Invocation

```bash
comfy-agent sql --sql "SELECT image FROM txt2img_empty USING zehra_1 PROFILE cinematic_portrait WHERE prompt='a cinematic portrait of a woman' AND seed=12345;"
```
