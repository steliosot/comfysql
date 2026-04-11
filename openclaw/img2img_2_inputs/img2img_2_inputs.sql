-- img2img_2_inputs sample commands
-- Run:
-- REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
-- comfysql sql remote --sql-file "${REPO_ROOT}/openclaw/img2img_2_inputs/img2img_2_inputs.sql"

-- prechecks (fail fast)
DESCRIBE WORKFLOW img2img_2_inputs;
DESCRIBE PRESET default_run FOR img2img_2_inputs;
DESCRIBE PROFILE standard_50mm;
DESCRIBE PROFILE dramatic_low_angle;
DESCRIBE CHARACTER char_matt;
DESCRIBE OBJECT obj_hat;

-- compile-only dry run
EXPLAIN SELECT image FROM img2img_2_inputs
USING default_run
CHARACTER char_matt
OBJECT obj_hat
PROFILE standard_50mm
WHERE prompt='a cinematic portrait of a woman carrying one luxury brown leather handbag, preserve identity and scene'
  AND seed=3301;

-- generation run
SELECT image FROM img2img_2_inputs
USING default_run
CHARACTER char_matt
OBJECT obj_hat
PROFILE dramatic_low_angle
WHERE prompt='dramatic cinematic portrait, preserve the same woman and realistic handbag integration'
  AND seed=3302;
