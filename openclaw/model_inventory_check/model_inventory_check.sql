-- model_inventory_check command pack
-- Run:
-- REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
-- comfysql sql remote --sql-file "${REPO_ROOT}/openclaw/model_inventory_check/model_inventory_check.sql"

SELECT name FROM models WHERE category='checkpoints' ORDER BY name ASC LIMIT 50;
SELECT name FROM models WHERE category='loras' ORDER BY name ASC LIMIT 50;
SELECT name FROM models WHERE category='vae' ORDER BY name ASC LIMIT 50;
