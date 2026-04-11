-- workflow_run_with_download command pack
-- Run:
-- REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
-- comfysql sql remote --sql-file "${REPO_ROOT}/openclaw/workflow_run_with_download/workflow_run_with_download.sql" --download-output --download-dir "${REPO_ROOT}/output"

-- prechecks (fail fast)
DESCRIBE WORKFLOW txt2img_empty_latent;
DESCRIBE PRESET default_run FOR txt2img_empty_latent;

SELECT image FROM txt2img_empty_latent
USING default_run
WHERE prompt='download run smoke prompt'
  AND seed=303;
