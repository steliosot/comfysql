---
name: img2img_reference
description: Run identity-preserving image-to-image generation with the img2img_reference ComfySQL workflow.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧍","requires":{"bins":["comfysql"]}}}
---

# img2img_reference

Use this skill when you want to transform a single reference image with prompt guidance.

## Preconditions

- `comfysql` is installed (`comfy-agent` compatibility alias is also supported).
- SQL workflow table exists:
  - `CREATE TABLE img2img_reference AS WORKFLOW '${REPO_ROOT}/input/workflows/img2img_reference.json';`
- Preset exists (recommended): `default_run`.

## Execution

Run the SQL examples in:

- `{baseDir}/img2img_reference.sql`

## Expected Output

- Run completes with `executed`.
- `validated ...` line appears before execution.
- Generated artifact is available through configured output behavior.


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
