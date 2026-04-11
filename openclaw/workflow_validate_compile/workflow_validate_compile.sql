-- workflow_validate_compile command pack
-- Run with compile-only:
-- REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
-- comfysql sql remote --compile-only --sql-file "${REPO_ROOT}/openclaw/workflow_validate_compile/workflow_validate_compile.sql"

-- prechecks (fail fast)
DESCRIBE WORKFLOW txt2img_empty_latent;
DESCRIBE WORKFLOW img2img_reference;
DESCRIBE PRESET default_run FOR txt2img_empty_latent;
DESCRIBE PRESET default_run FOR img2img_reference;
DESCRIBE CHARACTER char_matt;

EXPLAIN SELECT image FROM txt2img_empty_latent
USING default_run
WHERE prompt='compile-only smoke prompt'
  AND seed=101;

EXPLAIN SELECT image FROM img2img_reference
USING default_run
CHARACTER char_matt
WHERE prompt='compile-only img2img check'
  AND seed=202;
