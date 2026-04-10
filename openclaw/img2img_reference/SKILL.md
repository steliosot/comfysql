---
name: img2img_reference
description: Run identity-preserving image-to-image generation with the img2img_reference ComfySQL workflow.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧍","requires":{"bins":["comfy-agent"]}}}
---

# img2img_reference

Use this skill when you want to transform a single reference image with prompt guidance.

## Preconditions

- `comfy-agent` is installed.
- SQL workflow table exists:
  - `CREATE TABLE img2img_reference AS WORKFLOW '/Users/stelios/Downloads/ComfyUI-custom/input/workflows/img2img_reference.json';`
- Preset exists (recommended): `default_run`.

## Execution

Run the SQL examples in:

- `{baseDir}/img2img_reference.sql`

## Expected Output

- Run completes with `executed`.
- `validated ...` line appears before execution.
- Generated artifact is available through configured output behavior.

