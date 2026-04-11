-- preset_profile_manage command pack (no-create)
-- Run:
-- REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
-- comfysql sql remote --sql-file "${REPO_ROOT}/openclaw/preset_profile_manage/preset_profile_manage.sql"

SHOW PRESETS;
SHOW PROFILES;

-- prechecks (fail fast)
DESCRIBE PRESET default_run FOR txt2img_empty_latent;
DESCRIBE PROFILE standard_50mm;

-- Optional cleanup examples (uncomment when needed):
-- DROP PRESET old_style FOR txt2img_empty_latent;
-- DROP PROFILE old_profile;
