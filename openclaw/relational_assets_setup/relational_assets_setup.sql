-- relational_assets_setup command pack
-- Run:
-- REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
-- comfysql sql remote --sql-file "${REPO_ROOT}/openclaw/relational_assets_setup/relational_assets_setup.sql"

-- prechecks (fail fast)
DESCRIBE WORKFLOW img2img_reference;
DESCRIBE WORKFLOW img2img_2_inputs;

-- register reusable aliases
CREATE CHARACTER char_bets WITH image='bets.png';
CREATE CHARACTER char_matt WITH image='matt.png';
CREATE OBJECT obj_hat WITH image='sunday-afternoons-havana-hat-hat.jpg';

-- bind workflow slots once
CREATE SLOT subject FOR img2img_reference AS CHARACTER BINDING input_image;
CREATE SLOT subject FOR img2img_2_inputs AS CHARACTER BINDING 198.image;
CREATE SLOT hat FOR img2img_2_inputs AS OBJECT BINDING 213.image;

-- verify
SHOW CHARACTERS;
SHOW OBJECTS;
DESCRIBE CHARACTER char_matt;
DESCRIBE CHARACTER char_bets;
DESCRIBE OBJECT obj_hat;
