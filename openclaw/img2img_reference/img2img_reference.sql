-- img2img_reference sample commands
-- Run:
-- REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
-- comfy-agent sql remote --sql-file "${REPO_ROOT}/openclaw/img2img_reference/img2img_reference.sql"

-- prechecks (fail fast)
DESCRIBE WORKFLOW img2img_reference;
DESCRIBE PRESET default_run FOR img2img_reference;
DESCRIBE PROFILE portrait_85mm;
DESCRIBE PROFILE studio_hard_side;

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
