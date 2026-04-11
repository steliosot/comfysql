-- workflow_describe_introspect command pack
-- Run:
-- REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
-- comfysql sql remote --sql-file "${REPO_ROOT}/openclaw/workflow_describe_introspect/workflow_describe_introspect.sql"

SHOW WORKFLOWS;
DESCRIBE WORKFLOW txt2img_empty_latent;
DESCRIBE WORKFLOW img2img_reference;
DESCRIBE WORKFLOW img2img_2_inputs;
