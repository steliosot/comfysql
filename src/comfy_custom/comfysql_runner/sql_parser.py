from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


class SQLParseError(ValueError):
    pass


def _parse_error_with_examples(statement: str) -> SQLParseError:
    upper = statement.upper()
    examples = [
        "SELECT image FROM txt2img_empty WHERE seed=1;",
        "EXPLAIN SELECT image FROM txt2img_empty WHERE seed=1;",
        "SELECT image FROM img2img_controlnet USING default_run CHARACTER char_bets PROFILE goldenhour_backlight WHERE seed=1;",
        "SHOW TABLES;",
        "DESCRIBE WORKFLOW txt2img_empty;",
        "CREATE TABLE demo AS WORKFLOW '/abs/path/workflow.json';",
        "CREATE TEMPLATE txt2img AS WORKFLOW '/abs/path/workflow.json';",
        "CREATE TABLE txt2img AS TEMPLATE '/abs/path/workflow.json';",
        "SET META FOR txt2img_empty AS '{\"intent\":\"image_generation\"}';",
        "UNSET META FOR txt2img_empty;",
        "CREATE PRESET fast FOR txt2img_empty AS DEFAULTS;",
        "ALTER PRESET fast FOR txt2img_empty SET steps=10;",
        "CREATE PROFILE square_1x1 WITH width=1080 AND height=1080;",
        "SHOW QUERIES;",
        "CREATE QUERY quick AS SELECT image FROM txt2img_empty WHERE seed=1;",
    ]
    hint = " Expected one of:\n- " + "\n- ".join(examples)
    if "DESCRBIBE" in upper:
        return SQLParseError("Unsupported SQL statement. Did you mean `DESCRIBE`?" + hint)
    if upper.startswith("SELECT") and " FROM " not in upper:
        return SQLParseError("Invalid SELECT syntax: missing `FROM`." + hint)
    if upper.startswith("CREATE PRESET") and " FOR " in upper and " WITH " not in upper and " AS DEFAULTS" not in upper:
        return SQLParseError("Invalid CREATE PRESET syntax: use `WITH ...` or `AS DEFAULTS`." + hint)
    if upper.startswith("ALTER PRESET") and " SET " not in upper:
        return SQLParseError("Invalid ALTER PRESET syntax: missing `SET`." + hint)
    if upper.startswith("ALTER PROFILE") and " SET " not in upper:
        return SQLParseError("Invalid ALTER PROFILE syntax: missing `SET`." + hint)
    if upper.startswith("CREATE TABLE") and " AS WORKFLOW " not in upper and " AS TEMPLATE " not in upper:
        return SQLParseError("Invalid CREATE TABLE syntax: use `AS WORKFLOW '<path>'` or `AS TEMPLATE '<path>'`." + hint)
    if upper.startswith("SET META FOR") and " AS " not in upper:
        return SQLParseError("Invalid SET META syntax: use `SET META FOR <table> AS '<json>'`." + hint)
    return SQLParseError("Unsupported SQL statement." + hint)


@dataclass
class SelectQuery:
    output_name: str
    table_name: str
    where: dict[str, Any]
    where_raw: str | None = None
    source_alias: str | None = None
    preset_name: str | None = None
    character_name: str | None = None
    object_name: str | None = None
    profile_name: str | None = None
    order_by: tuple[str, str] | None = None
    limit: int | None = None
    explain: bool = False


@dataclass
class DescribeQuery:
    target: str


@dataclass
class DescribeTablesQuery:
    filter_kind: str = "all"


@dataclass
class RefreshSchemaQuery:
    pass


@dataclass
class PingComfyQuery:
    pass


@dataclass
class CreatePresetQuery:
    preset_name: str
    template_name: str
    params: dict[str, Any]


@dataclass
class CreatePresetDefaultsQuery:
    preset_name: str
    template_name: str


@dataclass
class CreateWorkflowTableQuery:
    table_name: str
    workflow_path: str
    kind: str = "workflow"


@dataclass
class DropTableQuery:
    table_name: str


@dataclass
class SetMetaQuery:
    table_name: str
    meta: dict[str, Any]


@dataclass
class UnsetMetaQuery:
    table_name: str


@dataclass
class AlterPresetQuery:
    preset_name: str
    template_name: str
    params: dict[str, Any]


@dataclass
class AlterProfileQuery:
    profile_name: str
    params: dict[str, Any]


@dataclass
class DropPresetQuery:
    preset_name: str
    template_name: str


@dataclass
class DescribePresetQuery:
    preset_name: str
    template_name: str


@dataclass
class CreateProfileQuery:
    profile_name: str
    params: dict[str, Any]


@dataclass
class DropProfileQuery:
    profile_name: str


@dataclass
class DescribeProfileQuery:
    profile_name: str


@dataclass
class ShowCharactersQuery:
    pass


@dataclass
class ShowObjectsQuery:
    pass


@dataclass
class DescribeCharacterQuery:
    character_name: str


@dataclass
class DescribeObjectQuery:
    object_name: str


@dataclass
class CreateCharacterQuery:
    character_name: str
    image_name: str


@dataclass
class CreateObjectQuery:
    object_name: str
    image_name: str


@dataclass
class CreateWorkflowSlotQuery:
    slot_name: str
    workflow_table: str
    slot_kind: str
    binding_key: str


@dataclass
class CreateQueryMacroQuery:
    name: str
    sql_text: str


@dataclass
class RunQueryMacroQuery:
    name: str


@dataclass
class DropQueryMacroQuery:
    name: str


@dataclass
class DescribeQueryMacroQuery:
    name: str


@dataclass
class ShowQueriesQuery:
    pass


SQLQuery = (
    SelectQuery
    | DescribeQuery
    | DescribeTablesQuery
    | RefreshSchemaQuery
    | PingComfyQuery
    | CreatePresetQuery
    | CreatePresetDefaultsQuery
    | CreateWorkflowTableQuery
    | DropTableQuery
    | SetMetaQuery
    | UnsetMetaQuery
    | AlterPresetQuery
    | AlterProfileQuery
    | DropPresetQuery
    | DescribePresetQuery
    | CreateProfileQuery
    | DropProfileQuery
    | DescribeProfileQuery
    | ShowCharactersQuery
    | ShowObjectsQuery
    | DescribeCharacterQuery
    | DescribeObjectQuery
    | CreateCharacterQuery
    | CreateObjectQuery
    | CreateWorkflowSlotQuery
    | CreateQueryMacroQuery
    | RunQueryMacroQuery
    | DropQueryMacroQuery
    | DescribeQueryMacroQuery
    | ShowQueriesQuery
)


def _split_conditions(where_clause: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(where_clause):
        ch = where_clause[i]
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue

        if where_clause[i : i + 3].upper() == "AND":
            prev = where_clause[i - 1] if i > 0 else " "
            nxt = where_clause[i + 3] if i + 3 < len(where_clause) else " "
            if prev.isspace() and nxt.isspace():
                part = "".join(buf).strip()
                if part:
                    parts.append(part)
                buf = []
                i += 3
                continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_value(raw: str) -> Any:
    text = raw.strip()

    if (text.startswith("'") and text.endswith("'")) or (
        text.startswith('"') and text.endswith('"')
    ):
        return text[1:-1]

    if text.lower() in ("true", "false"):
        return text.lower() == "true"

    if re.fullmatch(r"-?\d+", text):
        return int(text)

    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)

    return text


def _normalize(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def parse_sql(sql: str) -> SQLQuery:
    statement = _normalize(sql)
    upper = statement.upper()

    create_workflow_match = re.match(
        r"^CREATE\s+TABLE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+WORKFLOW\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if create_workflow_match:
        table_name = create_workflow_match.group(1)
        workflow_path = create_workflow_match.group(2).strip()
        if (workflow_path.startswith("'") and workflow_path.endswith("'")) or (
            workflow_path.startswith('"') and workflow_path.endswith('"')
        ):
            workflow_path = workflow_path[1:-1]
        return CreateWorkflowTableQuery(table_name=table_name, workflow_path=workflow_path, kind="workflow")

    create_template_table_match = re.match(
        r"^CREATE\s+TABLE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+TEMPLATE\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if create_template_table_match:
        table_name = create_template_table_match.group(1)
        workflow_path = create_template_table_match.group(2).strip()
        if (workflow_path.startswith("'") and workflow_path.endswith("'")) or (
            workflow_path.startswith('"') and workflow_path.endswith('"')
        ):
            workflow_path = workflow_path[1:-1]
        return CreateWorkflowTableQuery(table_name=table_name, workflow_path=workflow_path, kind="template")

    create_template_match = re.match(
        r"^CREATE\s+TEMPLATE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+WORKFLOW\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if create_template_match:
        table_name = create_template_match.group(1)
        workflow_path = create_template_match.group(2).strip()
        if (workflow_path.startswith("'") and workflow_path.endswith("'")) or (
            workflow_path.startswith('"') and workflow_path.endswith('"')
        ):
            workflow_path = workflow_path[1:-1]
        return CreateWorkflowTableQuery(table_name=table_name, workflow_path=workflow_path, kind="template")

    drop_table_match = re.match(
        r"^DROP\s+TABLE\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if drop_table_match:
        return DropTableQuery(table_name=drop_table_match.group(1))

    drop_workflow_match = re.match(
        r"^DROP\s+WORKFLOW\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if drop_workflow_match:
        return DropTableQuery(table_name=drop_workflow_match.group(1))

    set_meta_match = re.match(
        r"^SET\s+META\s+FOR\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if set_meta_match:
        table_name = set_meta_match.group(1)
        raw_payload = set_meta_match.group(2).strip()
        if (raw_payload.startswith("'") and raw_payload.endswith("'")) or (
            raw_payload.startswith('"') and raw_payload.endswith('"')
        ):
            raw_payload = raw_payload[1:-1]
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise SQLParseError(f"Invalid SET META payload: expected JSON object: {exc}") from exc
        if not isinstance(payload, dict):
            raise SQLParseError("Invalid SET META payload: expected a JSON object.")
        return SetMetaQuery(table_name=table_name, meta=payload)

    unset_meta_match = re.match(
        r"^UNSET\s+META\s+FOR\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if unset_meta_match:
        return UnsetMetaQuery(table_name=unset_meta_match.group(1))

    if upper in ("DESCRIBE TABLES", "SHOW TABLES"):
        return DescribeTablesQuery(filter_kind="all")
    if upper in ("SHOW WORKFLOWS", "DESCRIBE WORKFLOWS"):
        return DescribeTablesQuery(filter_kind="workflows")
    if upper == "SHOW QUERIES":
        return ShowQueriesQuery()
    if upper in ("SHOW TEMPLATES", "DESCRIBE TEMPLATES"):
        return DescribeTablesQuery(filter_kind="templates")
    if upper in ("SHOW NODES", "DESCRIBE NODES"):
        return DescribeTablesQuery(filter_kind="nodes")
    if upper == "SHOW MODELS":
        return DescribeTablesQuery(filter_kind="models")
    if upper in ("SHOW PRESETS", "DESCRIBE PRESETS"):
        return DescribeTablesQuery(filter_kind="presets")
    if upper in ("SHOW PROFILES", "DESCRIBE PROFILES"):
        return DescribeTablesQuery(filter_kind="profiles")
    if upper == "SHOW CHARACTERS":
        return ShowCharactersQuery()
    if upper == "SHOW OBJECTS":
        return ShowObjectsQuery()

    show_tables_match = re.match(
        r"^(?:SHOW|DESCRIBE)\s+TABLES\s+(all|nodes|templates|workflows|presets|profiles|models)$",
        statement,
        flags=re.IGNORECASE,
    )
    if show_tables_match:
        return DescribeTablesQuery(filter_kind=show_tables_match.group(1).lower())

    if upper == "REFRESH SCHEMA":
        return RefreshSchemaQuery()

    if upper == "PING COMFY":
        return PingComfyQuery()

    describe_workflow_match = re.match(
        r"^DESCRIBE\s+WORKFLOW\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if describe_workflow_match:
        return DescribeQuery(target=describe_workflow_match.group(1))

    show_workflow_match = re.match(
        r"^SHOW\s+WORKFLOW\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if show_workflow_match:
        return DescribeQuery(target=show_workflow_match.group(1))

    describe_match = re.match(r"^DESCRIBE\s+([a-zA-Z_][a-zA-Z0-9_]*)$", statement, flags=re.IGNORECASE)
    if describe_match:
        return DescribeQuery(target=describe_match.group(1))

    describe_preset_match = re.match(
        r"^DESCRIBE\s+PRESET\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+FOR\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if describe_preset_match:
        return DescribePresetQuery(
            preset_name=describe_preset_match.group(1),
            template_name=describe_preset_match.group(2),
        )

    show_preset_match = re.match(
        r"^SHOW\s+PRESET\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+FOR\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if show_preset_match:
        return DescribePresetQuery(
            preset_name=show_preset_match.group(1),
            template_name=show_preset_match.group(2),
        )

    describe_profile_match = re.match(
        r"^DESCRIBE\s+PROFILE\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if describe_profile_match:
        return DescribeProfileQuery(profile_name=describe_profile_match.group(1))

    describe_character_match = re.match(
        r"^DESCRIBE\s+CHARACTER\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if describe_character_match:
        return DescribeCharacterQuery(character_name=describe_character_match.group(1))

    describe_object_match = re.match(
        r"^DESCRIBE\s+OBJECT\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if describe_object_match:
        return DescribeObjectQuery(object_name=describe_object_match.group(1))

    create_character_match = re.match(
        r"^CREATE\s+CHARACTER\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+WITH\s+image\s*=\s*(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if create_character_match:
        return CreateCharacterQuery(
            character_name=create_character_match.group(1),
            image_name=str(_parse_value(create_character_match.group(2))),
        )

    create_object_match = re.match(
        r"^CREATE\s+OBJECT\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+WITH\s+image\s*=\s*(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if create_object_match:
        return CreateObjectQuery(
            object_name=create_object_match.group(1),
            image_name=str(_parse_value(create_object_match.group(2))),
        )

    create_slot_match = re.match(
        r"^CREATE\s+SLOT\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+FOR\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+(CHARACTER|OBJECT)\s+BINDING\s+([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)$",
        statement,
        flags=re.IGNORECASE,
    )
    if create_slot_match:
        return CreateWorkflowSlotQuery(
            slot_name=create_slot_match.group(1),
            workflow_table=create_slot_match.group(2),
            slot_kind=create_slot_match.group(3).lower(),
            binding_key=create_slot_match.group(4).lower(),
        )

    create_preset_match = re.match(
        r"^CREATE\s+PRESET\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+FOR\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+WITH\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if create_preset_match:
        preset_name = create_preset_match.group(1)
        template_name = create_preset_match.group(2)
        assignments = create_preset_match.group(3).strip()
        params: dict[str, Any] = {}
        for cond in _split_conditions(assignments):
            cm = re.match(r"^([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)\s*=\s*(.+)$", cond)
            if not cm:
                raise SQLParseError(f"Invalid preset assignment: {cond}")
            params[cm.group(1).lower()] = _parse_value(cm.group(2))
        return CreatePresetQuery(
            preset_name=preset_name,
            template_name=template_name,
            params=params,
        )

    alter_preset_match = re.match(
        r"^ALTER\s+PRESET\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+FOR\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+SET\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if alter_preset_match:
        preset_name = alter_preset_match.group(1)
        template_name = alter_preset_match.group(2)
        assignments = alter_preset_match.group(3).strip()
        params: dict[str, Any] = {}
        for cond in _split_conditions(assignments):
            cm = re.match(r"^([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)\s*=\s*(.+)$", cond)
            if not cm:
                raise SQLParseError(f"Invalid preset assignment: {cond}")
            params[cm.group(1).lower()] = _parse_value(cm.group(2))
        return AlterPresetQuery(
            preset_name=preset_name,
            template_name=template_name,
            params=params,
        )

    create_preset_defaults_match = re.match(
        r"^CREATE\s+PRESET\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+FOR\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+DEFAULTS$",
        statement,
        flags=re.IGNORECASE,
    )
    if create_preset_defaults_match:
        return CreatePresetDefaultsQuery(
            preset_name=create_preset_defaults_match.group(1),
            template_name=create_preset_defaults_match.group(2),
        )

    drop_preset_match = re.match(
        r"^DROP\s+PRESET\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+FOR\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if drop_preset_match:
        return DropPresetQuery(
            preset_name=drop_preset_match.group(1),
            template_name=drop_preset_match.group(2),
        )

    create_profile_match = re.match(
        r"^CREATE\s+PROFILE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+WITH\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if create_profile_match:
        profile_name = create_profile_match.group(1)
        assignments = create_profile_match.group(2).strip()
        params: dict[str, Any] = {}
        for cond in _split_conditions(assignments):
            cm = re.match(r"^([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)\s*=\s*(.+)$", cond)
            if not cm:
                raise SQLParseError(f"Invalid profile assignment: {cond}")
            params[cm.group(1).lower()] = _parse_value(cm.group(2))
        return CreateProfileQuery(profile_name=profile_name, params=params)

    alter_profile_match = re.match(
        r"^ALTER\s+PROFILE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+SET\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if alter_profile_match:
        profile_name = alter_profile_match.group(1)
        assignments = alter_profile_match.group(2).strip()
        params: dict[str, Any] = {}
        for cond in _split_conditions(assignments):
            cm = re.match(r"^([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)\s*=\s*(.+)$", cond)
            if not cm:
                raise SQLParseError(f"Invalid profile assignment: {cond}")
            params[cm.group(1).lower()] = _parse_value(cm.group(2))
        return AlterProfileQuery(profile_name=profile_name, params=params)

    drop_profile_match = re.match(
        r"^DROP\s+PROFILE\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if drop_profile_match:
        return DropProfileQuery(profile_name=drop_profile_match.group(1))

    create_query_match = re.match(
        r"^CREATE\s+QUERY\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if create_query_match:
        name = create_query_match.group(1)
        raw_sql = create_query_match.group(2).strip()
        if (raw_sql.startswith("'") and raw_sql.endswith("'")) or (raw_sql.startswith('"') and raw_sql.endswith('"')):
            raw_sql = raw_sql[1:-1]
        return CreateQueryMacroQuery(name=name, sql_text=raw_sql)

    run_query_match = re.match(
        r"^RUN\s+QUERY\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if run_query_match:
        return RunQueryMacroQuery(name=run_query_match.group(1))

    describe_query_match = re.match(
        r"^DESCRIBE\s+QUERY\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if describe_query_match:
        return DescribeQueryMacroQuery(name=describe_query_match.group(1))

    drop_query_match = re.match(
        r"^DROP\s+QUERY\s+([a-zA-Z_][a-zA-Z0-9_]*)$",
        statement,
        flags=re.IGNORECASE,
    )
    if drop_query_match:
        return DropQueryMacroQuery(name=drop_query_match.group(1))

    explain = False
    select_text = statement
    if re.match(r"^EXPLAIN\b", statement, flags=re.IGNORECASE):
        explain = True
        select_text = re.sub(r"^EXPLAIN\b\s*", "", statement, count=1, flags=re.IGNORECASE).strip()

    select_match = re.match(
        r"^SELECT\s+(?P<select>[a-zA-Z_][a-zA-Z0-9_]*)\s+FROM\s+(?P<from>[a-zA-Z_][a-zA-Z0-9_]*)(?:\s+(?:AS\s+)?(?P<alias>[a-zA-Z_][a-zA-Z0-9_]*))?(?:\s+USING\s+(?P<preset>[a-zA-Z_][a-zA-Z0-9_]*))?(?:\s+CHARACTER\s+(?P<character>[a-zA-Z_][a-zA-Z0-9_]*))?(?:\s+OBJECT\s+(?P<object>[a-zA-Z_][a-zA-Z0-9_]*))?(?:\s+PROFILE\s+(?P<profile>[a-zA-Z_][a-zA-Z0-9_]*))?\s*(?:WHERE\s+(?P<where>.+))?$",
        select_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not select_match:
        raise _parse_error_with_examples(statement)

    output_name = select_match.group("select")
    table_name = select_match.group("from")
    source_alias = select_match.group("alias")
    preset_name = select_match.group("preset")
    character_name = select_match.group("character")
    object_name = select_match.group("object")
    profile_name = select_match.group("profile")
    where_text = select_match.group("where")

    order_by: tuple[str, str] | None = None
    limit: int | None = None
    where_raw: str | None = None

    if where_text:
        tail = where_text.strip()
        limit_match = re.search(r"\s+LIMIT\s+(\d+)\s*$", tail, flags=re.IGNORECASE)
        if limit_match:
            limit = int(limit_match.group(1))
            tail = tail[: limit_match.start()].strip()
        order_match = re.search(
            r"\s+ORDER\s+BY\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s+(ASC|DESC))?\s*$",
            tail,
            flags=re.IGNORECASE,
        )
        if order_match:
            order_by = (order_match.group(1).lower(), (order_match.group(2) or "asc").lower())
            tail = tail[: order_match.start()].strip()
        where_text = tail

    where: dict[str, Any] = {}
    if where_text:
        simple = True
        for cond in _split_conditions(where_text.strip()):
            cm = re.match(r"^([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)\s*=\s*(.+)$", cond)
            if not cm:
                simple = False
                break
            where[cm.group(1).lower()] = _parse_value(cm.group(2))
        if not simple:
            where = {}
            where_raw = where_text.strip()

    return SelectQuery(
        output_name=output_name.lower(),
        table_name=table_name,
        where=where,
        where_raw=where_raw,
        source_alias=source_alias.lower() if source_alias else None,
        preset_name=preset_name.lower() if preset_name else None,
        character_name=character_name.lower() if character_name else None,
        object_name=object_name.lower() if object_name else None,
        profile_name=profile_name.lower() if profile_name else None,
        order_by=order_by,
        limit=limit,
        explain=explain,
    )
