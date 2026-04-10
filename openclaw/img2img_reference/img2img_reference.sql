-- img2img_reference sample commands
-- Run:
-- comfy-agent sql remote --sql-file /Users/stelios/Downloads/ComfyUI-custom/openclaw/img2img_reference/img2img_reference.sql

-- compile-only dry run
EXPLAIN SELECT image FROM img2img_reference
USING default_run
PROFILE portrait_85mm
WHERE prompt='a cinematic portrait of a woman, realistic skin, preserve identity'
  AND seed=2201;

-- generation run
SELECT image FROM img2img_reference
USING default_run
PROFILE studio_hard_side
WHERE prompt='luxury portrait with dramatic studio side-lighting, preserve facial identity'
  AND seed=2202;

