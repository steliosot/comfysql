---
name: img2img_2_inputs
description: Run multi-reference identity-preserving image-to-image generation with the img2img_2_inputs ComfySQL workflow.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧩","requires":{"bins":["comfy-agent"]}}}
---

# img2img_2_inputs

Use this skill when a workflow combines two image references plus prompt guidance.

## Preconditions

- `comfy-agent` is installed.
- SQL workflow table exists:
  - `CREATE TABLE img2img_2_inputs AS WORKFLOW '/Users/stelios/Downloads/ComfyUI-custom/input/workflows/img2img_2_inputs.json';`
- Preset exists (recommended): `default_run`.

## Execution

Run the SQL examples in:

- `{baseDir}/img2img_2_inputs.sql`

## Expected Output

- Submit lifecycle completes with `executed`.
- Validation summary is printed.
- Output is generated according to your SQL output mode/download settings.

