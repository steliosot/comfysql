# ComfySQL CLI Commands

Single-file reference for `comfysql` (primary) and `comfy-agent` (compatibility alias).

Output behavior:

- Interactive terminal: clean colorized status/success/warning/error lines.
- Non-interactive runs: plain text output (no forced ANSI escape codes).
- Known failures include a concise `hint:` line with a concrete next command.
- Automation mode: `--output json` on `status`, `doctor`, `sql`, `sql-report`, `copy-assets`.
- Extended preflight: `comfysql doctor <server> --full`.

Exit code contract:

- `0` success
- `2` parse/usage/config input errors
- `3` auth errors
- `4` network/connectivity errors
- `5` validation errors
- `6` runtime/internal execution errors
- `130` cancelled/interrupted

## Top-Level Commands

```bash
comfysql -h
```

Compatibility:

```bash
comfy-agent -h
```

Available commands:

- `status`
- `doctor`
- `pull`
- `copy-assets`
- `bind-character`
- `sync`
- `download`
- `submit`
- `validate`
- `sql`
- `sql-report`
- `config`

## CLI Command Reference

## Health / Connectivity

```bash
comfysql status [server] [--config <path>] [--host <host>] [--port <port>] [--output {text,json}]
comfysql doctor [server] [--config <path>] [--host <host>] [--port <port>] [--timeout <seconds>] [--full] [--output {text,json}]
comfysql sync [server] [--config <path>] [--host <host>] [--port <port>] [--start-timeout <seconds>] [--timeout <seconds>]
```

## Asset Operations

```bash
comfysql copy-assets [server] [source] [--all] [--dry-run] [--yes] [--output {text,json}] [--config <path>] [--host <host>] [--port <port>] [--timeout <seconds>]
```

Notes:

- Use `copy-assets` (hyphen), not `copy_assets`.
- `source` is positional, not `--source`.
- Canonical local asset folder is `input/assets`.
- `--all` copies all files from local `./input/assets`.

Examples:

```bash
comfysql copy-assets remote --all
comfysql copy-assets remote input/assets/bets.png
```

## Workflow Binding Compatibility Command

```bash
comfysql bind-character [server] --workflow <workflow_table> --character <alias> --image <file> [--binding <node.input>] [--upload] [--yes] [--config <path>] [--host <host>] [--port <port>] [--timeout <seconds>]
```

Note:

- This is still supported for legacy per-workflow binding.
- Preferred model is relational SQL (`CREATE CHARACTER/OBJECT/SLOT`) documented below.

## Models / Pull

```bash
comfysql pull [--config <hf_pull_config.json>] [--yes] [--dry-run]
```

## Validate / Submit

```bash
comfysql validate [server] [--config <path>] [--host <host>] [--port <port>] <workflow>
comfysql submit [server] [--config <path>] [--host <host>] [--port <port>] [--timeout <seconds>] [--no-cache] [--skip-validate] <workflow>
```

## Download by URL

```bash
comfysql download [server] --url <absolute-url-or-/view?...> [--output <local-file>] [--config <path>] [--host <host>] [--port <port>] [--timeout <seconds>]
```

## SQL Runner

```bash
comfysql sql [server] [--config <path>]
comfysql sql [server] --sql "<statement>;" [--output {text,json}]
comfysql sql [server] --sql-file <file.sql>
```

SQL runner flags:

- `--show-tables {all,workflows,templates,nodes,presets,profiles,models}`
- `--compile-only`
- `--dry-run` (alias of `--compile-only`)
- `--no-cache`
- `-y, --yes`
- `--upload-mode {strict,warn,off}`
- `--download-output`
- `--output-mode {none,download}`
- `--download-dir <path>`
- `--timeout <seconds>`

## SQL Report Command

```bash
comfysql sql-report [server] --sql "<single-statement>;" [--report <path.md>] [--title <title>] [--image <path>] [--download-output] [--download-dir <path>] [--upload-mode {strict,warn,off}] [--compile-only] [--no-cache] [--output {text,json}] [--config <path>] [--host <host>] [--port <port>] [--timeout <seconds>]
comfysql sql-report [server] --sql-file <file.sql> [same-flags...]
```

## Config

```bash
comfysql config init
```

---

## ComfySQL Terminal Behavior

Start terminal:

```bash
comfysql sql remote
```

Terminal commands:

- Exit: `.exit` or `.quit`
- Clear: `clear`, `clear;`, or `.clear`

Statement terminators:

- One-line SQL can execute without `;` if complete.
- Multi-line SQL should end with `;` to execute.

---

## ComfySQL Statement Reference

## Discovery

```sql
SHOW TABLES;
SHOW TABLES workflows;
SHOW TABLES templates;
SHOW TABLES nodes;
SHOW TABLES presets;
SHOW TABLES profiles;
SHOW TABLES models;

SHOW WORKFLOWS;
SHOW TEMPLATES;
SHOW NODES;
SHOW PRESETS;
SHOW PROFILES;
SHOW MODELS;

SHOW CHARACTERS;
SHOW OBJECTS;

REFRESH SCHEMA;
PING COMFY;
```

## Describe

```sql
DESCRIBE <target>;
DESCRIBE WORKFLOW <table>;
SHOW WORKFLOW <table>;

DESCRIBE PRESET <preset> FOR <table>;
SHOW PRESET <preset> FOR <table>;
DESCRIBE PROFILE <profile>;

DESCRIBE CHARACTER <char_alias>;
DESCRIBE OBJECT <obj_alias>;
```

## Workflow Registration

```sql
CREATE TABLE <table> AS WORKFLOW '<path-to-workflow.json>';
CREATE TEMPLATE <table> AS WORKFLOW '<path-to-workflow.json>';
CREATE TABLE <table> AS TEMPLATE '<path-to-workflow.json>';

DROP TABLE <table>;
DROP WORKFLOW <table>;

SET META FOR <table> AS '{"intent":"image_generation"}';
UNSET META FOR <table>;
```

Template note:

- Template syntax is supported for compatibility.
- Recommended primary flow is workflow table + presets/profiles + relational assets.

## Presets

```sql
CREATE PRESET <preset> FOR <table> WITH key=value AND key2='value';
CREATE PRESET <preset> FOR <table> AS DEFAULTS;
ALTER PRESET <preset> FOR <table> SET key=value AND key2='value';
DROP PRESET <preset> FOR <table>;
```

## Profiles

```sql
CREATE PROFILE <profile> WITH key=value AND key2='value';
ALTER PROFILE <profile> SET key=value AND key2='value';
DROP PROFILE <profile>;
```

## Query Macros

```sql
SHOW QUERIES;
CREATE QUERY <name> AS <sql>;
DESCRIBE QUERY <name>;
RUN QUERY <name>;
DROP QUERY <name>;
```

## Relational Assets (Preferred)

1. Copy assets to remote:

```bash
comfysql copy-assets remote --all
```

2. Register reusable aliases:

```sql
CREATE CHARACTER char_bets WITH image='bets.png';
CREATE CHARACTER char_matt WITH image='matt.png';
CREATE OBJECT obj_hat WITH image='sunday-afternoons-havana-hat-hat.jpg';
```

3. Map workflow slots once:

```sql
CREATE SLOT subject FOR img2img_reference AS CHARACTER BINDING input_image;
CREATE SLOT subject FOR img2img_2_inputs AS CHARACTER BINDING 198.image;
CREATE SLOT hat FOR img2img_2_inputs AS OBJECT BINDING 213.image;
```

4. Reuse directly in queries:

```sql
SELECT image
FROM img2img_reference
USING default_run
CHARACTER char_matt
PROFILE goldenhour_backlight
WHERE prompt='cinematic portrait of Matt in central London at sunset'
  AND seed=123
  AND filename_prefix='img2img_matt_london_123';
```

```sql
SELECT image
FROM img2img_2_inputs
USING default_run
CHARACTER char_matt
OBJECT obj_hat
PROFILE goldenhour_backlight
WHERE prompt='cinematic portrait of Matt wearing a summer hat in central London at golden hour'
  AND seed=123
  AND filename_prefix='img2img2_matt_hat_123';
```

## SELECT / EXPLAIN

General form:

```sql
SELECT <output>
FROM <table>
[AS <alias>]
[USING <preset>]
[CHARACTER <char_alias>]
[OBJECT <obj_alias>]
[PROFILE <profile>]
[WHERE ...];

EXPLAIN SELECT ...;
```

Models table supports:

- `ORDER BY <category|name|path|folder> [ASC|DESC]`
- `LIMIT <n>`

Example:

```sql
SELECT name FROM models WHERE category='checkpoints' ORDER BY name DESC LIMIT 5;
```

Compatibility note:

- Legacy shorthand `USING char_*` still works where supported.
- Explicit `CHARACTER <name>` is preferred.

---

## Download Behavior Notes

- `--download-output` or `--output-mode download` downloads generated outputs after `SELECT`.
- On servers where `/history` is auth-restricted, fallback may use filename prefixes.
- For predictable per-run downloads, set a unique `filename_prefix` in `WHERE`.
