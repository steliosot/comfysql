-- txt2img_empty_latent sample commands
-- Run:
-- comfy-agent sql remote --sql-file /Users/stelios/Downloads/ComfyUI-custom/openclaw/txt2img_empty_latent/txt2img_empty_latent.sql

-- compile-only dry run
EXPLAIN SELECT image FROM txt2img_empty_latent
USING default_run
PROFILE standard_50mm
WHERE prompt='a cinematic portrait of a woman with natural skin texture'
  AND seed=1101;

-- generation run
SELECT image FROM txt2img_empty_latent
USING rapid_grid_512
PROFILE goldenhour_backlight
WHERE prompt='a warm golden-hour portrait, fashion editorial style'
  AND seed=1102
  AND batch_size=1;

