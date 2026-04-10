-- txt2img_empty_latent sample commands
-- Run:
-- REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
-- comfy-agent sql remote --sql-file "${REPO_ROOT}/openclaw/txt2img_empty_latent/txt2img_empty_latent.sql"

-- prechecks (fail fast)
DESCRIBE WORKFLOW txt2img_empty_latent;
DESCRIBE PRESET default_run FOR txt2img_empty_latent;
DESCRIBE PRESET rapid_grid_512 FOR txt2img_empty_latent;
DESCRIBE PROFILE standard_50mm;
DESCRIBE PROFILE goldenhour_backlight;

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
