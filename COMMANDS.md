# Comfy Agent Commands

This file is the command reference for `comfy-agent` and ComfySQL.

## CLI Commands

## Global

- `comfy-agent -h`
- `comfy-agent <command> -h`

## Connection / Health

- `comfy-agent status [server] [--config <path>] [--host <host>] [--port <port>]`
- `comfy-agent doctor [server] [--config <path>] [--host <host>] [--port <port>] [--timeout <seconds>]`

Notes:
- `doctor` checks health, `/object_info`, `/models`, websocket, and auth-header presence.

## Server Control (Remote-only mode)

- `comfy-agent stop ...`
- `comfy-agent restart ...`

Notes:
- These commands are currently exposed but intentionally unsupported in remote-only mode.

## Model / Asset Operations

- `comfy-agent pull [--config <hf_pull_config.json>] [--yes] [--dry-run]`
- `comfy-agent copy-assets [server] [<source>] [--all] [--dry-run] [--timeout <seconds>] [--config <path>] [--host <host>] [--port <port>]`
- `comfy-agent sync [server] [--config <path>] [--host <host>] [--port <port>] [--start-timeout <seconds>] [--timeout <seconds>]`

## Workflow Execution

- `comfy-agent validate <workflow.json> [server] [--config <path>] [--host <host>] [--port <port>]`
- `comfy-agent submit <workflow.json> [server] [--config <path>] [--host <host>] [--port <port>] [--timeout <seconds>] [--no-cache] [--skip-validate]`

## SQL Runner

- `comfy-agent sql [server] [--config <path>]`
- `comfy-agent sql [server] --sql "<statement>;"`
- `comfy-agent sql [server] --sql-file <file.sql>`

SQL runner flags:
- `--show-tables {all,workflows,templates,nodes,presets,profiles,models}`
- `--compile-only`
- `--dry-run` (alias of `--compile-only`)
- `--no-cache`
- `-y, --yes` (skip destructive SQL confirmation)
- `--upload-mode {strict,warn,off}`
- `--download-output`
- `--output-mode {none,download}`
- `--download-dir <path>`
- `--timeout <seconds>`

## Config

- `comfy-agent config init [--path <path>] [--force]`

---

## ComfySQL Specification

Each statement ends with `;`.

In interactive mode:
- Start with `comfy-agent sql <server>`
- Exit with `.exit` or `.quit`
- Clear screen with `clear`, `clear;`, or `.clear`

## Schema / Discovery

- `SHOW TABLES;`
- `SHOW TABLES workflows;`
- `SHOW TABLES templates;`
- `SHOW TABLES nodes;`
- `SHOW TABLES presets;`
- `SHOW TABLES profiles;`
- `SHOW TABLES models;`

Also supported:
- `DESCRIBE TABLES;`
- `SHOW WORKFLOWS;`
- `SHOW TEMPLATES;`
- `SHOW NODES;`
- `SHOW PRESETS;`
- `SHOW PROFILES;`
- `SHOW MODELS;`

- `REFRESH SCHEMA;`
- `PING COMFY;`

## Describe

- `DESCRIBE <target>;`  
  where target can be a workflow table, template, node class, or `models`
- `DESCRIBE WORKFLOW <table>;`
- `SHOW WORKFLOW <table>;` (alias)
- `DESCRIBE PRESET <preset> FOR <table>;`
- `SHOW PRESET <preset> FOR <table>;` (alias)
- `DESCRIBE PROFILE <profile>;`

## Workflow Tables

- `CREATE TABLE <table> AS WORKFLOW '<absolute-or-relative-path-to-json>';`
- `CREATE TABLE <table> AS TEMPLATE '<absolute-or-relative-path-to-json>';`
- `CREATE TEMPLATE <table> AS WORKFLOW '<absolute-or-relative-path-to-json>';`
- `DROP TABLE <table>;`
- `DROP WORKFLOW <table>;` (alias)
- `SET META FOR <table> AS '<json-object>';`
- `UNSET META FOR <table>;`

Notes:
- Template creation captures workflow default input values (stored with the template entry).
- If the source workflow JSON contains top-level `"meta": {...}`, it is imported automatically.
- You can materialize those defaults into a preset with:
  - `CREATE PRESET <preset> FOR <template_or_table> AS DEFAULTS;`

## Presets

- `CREATE PRESET <preset> FOR <table> WITH key=value AND key2='value';`
- `CREATE PRESET <preset> FOR <table> AS DEFAULTS;`
- `ALTER PRESET <preset> FOR <table> SET key=value AND key2='value';`
- `DROP PRESET <preset> FOR <table>;`

## Profiles

- `CREATE PROFILE <profile> WITH key=value AND key2='value';`
- `ALTER PROFILE <profile> SET key=value AND key2='value';`
- `DROP PROFILE <profile>;`

## Query Macros

- `SHOW QUERIES;`
- `CREATE QUERY <name> AS <sql>;`
- `DESCRIBE QUERY <name>;`
- `RUN QUERY <name>;`
- `DROP QUERY <name>;`

## SELECT / EXPLAIN

- `SELECT <output> FROM <table> [AS <alias>] [USING <preset>] [PROFILE <profile>] [WHERE ...];`
- `EXPLAIN SELECT <output> FROM <table> ...;`

Models table supports additional clauses:
- `ORDER BY <category|name|path|folder> [ASC|DESC]`
- `LIMIT <n>`

Example:
- `SELECT name FROM models WHERE category='checkpoints' ORDER BY name DESC LIMIT 5;`

## Auto Upload / Output Download Behavior

For SQL `SELECT`:
- Local file paths bound to supported asset fields are auto-uploaded before submit.
- Upload policy is controlled by `--upload-mode`.
- Output file download is enabled with `--download-output` or `--output-mode download`.
- Download results report both successes and failures (partial downloads are preserved). 
