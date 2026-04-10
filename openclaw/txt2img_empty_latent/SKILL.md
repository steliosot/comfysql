---
name: txt2img_empty_latent
description: Run text-to-image generation through the txt2img_empty_latent ComfySQL workflow with preset/profile combinations.
user-invocable: true
metadata: {"openclaw":{"emoji":"🖼️","requires":{"bins":["comfy-agent"]}}}
---

# txt2img_empty_latent

Use this skill to generate images from the `txt2img_empty_latent` workflow table via ComfySQL.

## Preconditions

- `comfy-agent` is installed.
- SQL workflow table exists:
  - `CREATE TABLE txt2img_empty_latent AS WORKFLOW '${REPO_ROOT}/input/workflows/txt2img_empty_latent.json';`
- Optional presets/profiles exist (for example `default_run`, `rapid_grid_512`, `standard_50mm`).

## Execution

Run the SQL examples in:

- `{baseDir}/txt2img_empty_latent.sql`

## Expected Output

- `submitted -> running -> executed` progress in CLI.
- `validated ...` summary.
- `api_prompt: ...` artifact path.


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
