-- comfysql_query_ops read-only command pack
-- Run:
-- comfy-agent sql remote --sql-file /Users/stelios/Downloads/ComfyUI-custom/openclaw/comfysql_query_ops/comfysql_query_ops.sql

-- 1) inventory
SHOW TABLES;
SHOW WORKFLOWS;
SHOW PRESETS;
SHOW PROFILES;

-- 2) workflow + metadata inspection
DESCRIBE WORKFLOW txt2img_empty_latent;
DESCRIBE WORKFLOW img2img_reference;
DESCRIBE WORKFLOW img2img_2_inputs;

-- 3) preset/profile inspection
DESCRIBE PRESET default_run FOR txt2img_empty_latent;
DESCRIBE PROFILE standard_50mm;

-- 4) dry-run explain before generation
EXPLAIN SELECT image FROM txt2img_empty_latent
USING default_run
PROFILE standard_50mm
WHERE prompt='diagnostic smoke prompt'
  AND seed=9001;

-- 5) models inventory quick check
SELECT name FROM models WHERE category='checkpoints' ORDER BY name ASC LIMIT 20;
