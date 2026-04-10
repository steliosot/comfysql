-- img2img_2_inputs sample commands
-- Run:
-- comfy-agent sql remote --sql-file /Users/stelios/Downloads/ComfyUI-custom/openclaw/img2img_2_inputs/img2img_2_inputs.sql

-- compile-only dry run
EXPLAIN SELECT image FROM img2img_2_inputs
USING default_run
PROFILE standard_50mm
WHERE prompt='a cinematic portrait of a woman carrying one luxury brown leather handbag, preserve identity and scene'
  AND seed=3301;

-- generation run
SELECT image FROM img2img_2_inputs
USING default_run
PROFILE dramatic_low_angle
WHERE prompt='dramatic cinematic portrait, preserve the same woman and realistic handbag integration'
  AND seed=3302;

