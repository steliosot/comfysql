---
name: img2img_2_inputs
description: Run multi-reference identity-preserving image-to-image generation with the img2img_2_inputs ComfySQL workflow.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧩","requires":{"bins":["comfysql"]}}}
---

# img2img_2_inputs

Use this skill when a workflow combines two image references plus prompt guidance.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- SQL workflow table exists:
  - `CREATE TABLE img2img_2_inputs AS WORKFLOW '${REPO_ROOT}/input/workflows/img2img_2_inputs.json';`
- Preset exists (recommended): `default_run`.

## Execution

Run the SQL examples in:

- `{baseDir}/img2img_2_inputs.sql`

## Expected Output

- Submit lifecycle completes with `executed`.
- Validation summary is printed.
- Output is generated according to your SQL output mode/download settings.


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
