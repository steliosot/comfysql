from __future__ import annotations

import json
from pathlib import Path

import pytest

from comfy_custom.sql_engine import (
    LocalComfySQLEngine,
    PresetRegistry,
    ProfileRegistry,
    SQLEngineError,
    WorkflowRegistry,
)


def _make_engine(tmp_path: Path) -> LocalComfySQLEngine:
    comfy_dir = tmp_path / "comfy-custom" / "comfyui-core"
    comfy_dir.mkdir(parents=True, exist_ok=True)
    (comfy_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")
    state_dir = tmp_path / "comfy-custom" / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return LocalComfySQLEngine(
        comfy_dir=comfy_dir,
        state_dir=state_dir,
        host="127.0.0.1",
        port=8188,
        ensure_server_running=lambda host, port: None,
        validate_api_prompt=lambda p: p,
        submit_api_prompt=lambda workflow, host, port, timeout, no_cache: None,
    )


def test_workflow_registry_roundtrip(tmp_path: Path) -> None:
    registry = WorkflowRegistry(tmp_path / "sql_registry.json")
    wf = tmp_path / "wf.json"
    wf.write_text("{}", encoding="utf-8")
    registry.create_table("my_table", wf, meta={"intent": "image_generation"})
    loaded = registry.get("my_table")
    assert loaded is not None
    assert loaded.table == "my_table"
    assert Path(loaded.workflow_path) == wf
    assert loaded.meta == {"intent": "image_generation"}
    assert registry.drop_table("my_table") is True
    assert registry.get("my_table") is None


def test_workflow_registry_migrates_v1_to_v2(tmp_path: Path) -> None:
    registry_path = tmp_path / "sql_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "tables": {"demo": {"workflow_path": "/tmp/demo.json", "created_at": 1.0}},
            }
        ),
        encoding="utf-8",
    )
    registry = WorkflowRegistry(registry_path)
    loaded = registry.get("demo")
    assert loaded is not None
    assert loaded.meta == {}
    migrated = json.loads(registry_path.read_text(encoding="utf-8"))
    assert migrated["version"] == 3
    assert isinstance(migrated.get("tables"), list)


def test_workflow_registry_migrates_v2_to_v3_with_empty_meta(tmp_path: Path) -> None:
    registry_path = tmp_path / "sql_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": 2,
                "tables": [
                    {
                        "table": "demo2",
                        "workflow_path": "/tmp/demo2.json",
                        "created_at": 2.0,
                        "kind": "workflow",
                        "default_params": {"seed": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = WorkflowRegistry(registry_path)
    loaded = registry.get("demo2")
    assert loaded is not None
    assert loaded.meta == {}
    migrated = json.loads(registry_path.read_text(encoding="utf-8"))
    assert migrated["version"] == 3
    assert isinstance(migrated.get("tables"), list)


def test_workflow_registry_rejects_future_version(tmp_path: Path) -> None:
    registry_path = tmp_path / "sql_registry.json"
    registry_path.write_text(json.dumps({"version": 99, "tables": []}), encoding="utf-8")
    registry = WorkflowRegistry(registry_path)
    with pytest.raises(SQLEngineError):
        registry.load()


def test_preset_registry_roundtrip(tmp_path: Path) -> None:
    registry = PresetRegistry(tmp_path / "sql_presets.json")
    spec = registry.upsert(
        template_name="txt2img_empty",
        preset_name="fast",
        params={"seed": 1, "cfg": 8},
    )
    assert spec.template_name == "txt2img_empty"
    assert spec.preset_name == "fast"
    loaded = registry.get("txt2img_empty", "fast")
    assert loaded is not None
    assert loaded.params["seed"] == 1
    assert registry.delete("txt2img_empty", "fast") is True
    assert registry.get("txt2img_empty", "fast") is None


def test_profile_registry_roundtrip(tmp_path: Path) -> None:
    registry = ProfileRegistry(tmp_path / "sql_profiles.json")
    spec = registry.upsert(
        profile_name="portrait",
        params={"lens": "50mm (Standard)", "camera_angle": "Low Angle"},
    )
    assert spec.profile_name == "portrait"
    loaded = registry.get("portrait")
    assert loaded is not None
    assert loaded.params["lens"] == "50mm (Standard)"
    assert registry.delete("portrait") is True
    assert registry.get("portrait") is None


def test_preset_and_profile_registry_reject_future_version(tmp_path: Path) -> None:
    preset_path = tmp_path / "sql_presets.json"
    preset_path.write_text(json.dumps({"version": 99, "presets": []}), encoding="utf-8")
    with pytest.raises(SQLEngineError):
        PresetRegistry(preset_path).load()

    profile_path = tmp_path / "sql_profiles.json"
    profile_path.write_text(json.dumps({"version": 99, "profiles": []}), encoding="utf-8")
    with pytest.raises(SQLEngineError):
        ProfileRegistry(profile_path).load()


def test_parse_create_drop_sql(tmp_path: Path) -> None:
    from comfy_custom.comfysql_runner.sql_parser import parse_sql

    parsed = parse_sql("CREATE TABLE demo AS WORKFLOW './x.json';")
    assert parsed.table_name == "demo"
    assert parsed.workflow_path == "./x.json"
    assert parsed.kind == "workflow"

    parsed_template = parse_sql("CREATE TEMPLATE demo_t AS WORKFLOW './x.json';")
    assert parsed_template.table_name == "demo_t"
    assert parsed_template.workflow_path == "./x.json"
    assert parsed_template.kind == "template"

    parsed_table_template = parse_sql("CREATE TABLE demo_t2 AS TEMPLATE './x.json';")
    assert parsed_table_template.table_name == "demo_t2"
    assert parsed_table_template.kind == "template"

    parsed_drop = parse_sql("DROP TABLE demo;")
    assert parsed_drop.table_name == "demo"

    meta_set = parse_sql("SET META FOR demo AS '{\"intent\":\"image_generation\"}';")
    assert meta_set.table_name == "demo"
    assert meta_set.meta["intent"] == "image_generation"

    meta_unset = parse_sql("UNSET META FOR demo;")
    assert meta_unset.table_name == "demo"

    with pytest.raises(Exception):
        parse_sql("SET META FOR demo AS '{not-json}';")


def test_compile_workflow_table_auto_selects_ambiguous_text_binding(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf.json"
    wf.write_text(
        json.dumps(
            {
                "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a"}},
                "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "b"}},
            }
        ),
        encoding="utf-8",
    )
    spec = engine.registry.create_table("wf_table", wf)
    patched = engine._compile_workflow_table(table_spec=spec, where={"text": "new"})
    assert patched["1"]["inputs"]["text"] == "new"


def test_compile_workflow_table_accepts_alias_prefix_and_semantic_seed(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf2.json"
    wf.write_text(
        json.dumps(
            {
                "3": {"class_type": "KSampler", "inputs": {"seed": 5, "steps": 20}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
            }
        ),
        encoding="utf-8",
    )
    spec = engine.registry.create_table("txt2img_empty", wf)
    patched = engine._compile_workflow_table_with_alias(
        table_spec=spec,
        where={"txt2img_empty.seed": 12345, "prompt": "a cinematic portrait"},
        source_alias="txt2img_empty",
    )
    assert patched["3"]["inputs"]["seed"] == 12345
    assert patched["6"]["inputs"]["text"] == "a cinematic portrait"


def test_sql_parser_supports_from_alias_and_dotted_where(tmp_path: Path) -> None:
    from comfy_custom.comfysql_runner.sql_parser import parse_sql

    q = parse_sql("SELECT image FROM txt2img_empty AS t WHERE t.seed=1 AND 6.text='x';")
    assert q.table_name == "txt2img_empty"
    assert q.source_alias == "t"
    assert q.where["t.seed"] == 1
    assert q.where["6.text"] == "x"

    q2 = parse_sql("SELECT image FROM txt2img_empty USING fast WHERE seed=5;")
    assert q2.table_name == "txt2img_empty"
    assert q2.preset_name == "fast"
    assert q2.where["seed"] == 5

    q3 = parse_sql("SELECT image FROM txt2img_empty USING fast PROFILE portrait WHERE seed=7;")
    assert q3.table_name == "txt2img_empty"
    assert q3.preset_name == "fast"
    assert q3.profile_name == "portrait"
    assert q3.where["seed"] == 7


def test_sql_parser_supports_show_tables_filter(tmp_path: Path) -> None:
    from comfy_custom.comfysql_runner.sql_parser import parse_sql

    q = parse_sql("SHOW TABLES templates;")
    assert q.filter_kind == "templates"

    q2 = parse_sql("SHOW TABLES presets;")
    assert q2.filter_kind == "presets"

    q3 = parse_sql("SHOW TABLES profiles;")
    assert q3.filter_kind == "profiles"

    q4 = parse_sql("SHOW PROFILES;")
    assert q4.filter_kind == "profiles"

    q5 = parse_sql("SHOW PRESETS;")
    assert q5.filter_kind == "presets"

    q6 = parse_sql("SHOW NODES;")
    assert q6.filter_kind == "nodes"


def test_sql_parser_supports_preset_commands(tmp_path: Path) -> None:
    from comfy_custom.comfysql_runner.sql_parser import parse_sql

    c = parse_sql(
        "CREATE PRESET fast FOR txt2img_empty WITH checkpoint='juggernaut_reborn.safetensors' AND steps=20;"
    )
    assert c.preset_name == "fast"
    assert c.template_name == "txt2img_empty"
    assert c.params["steps"] == 20

    d = parse_sql("DESCRIBE PRESET fast FOR txt2img_empty;")
    assert d.preset_name == "fast"
    assert d.template_name == "txt2img_empty"

    drop = parse_sql("DROP PRESET fast FOR txt2img_empty;")
    assert drop.preset_name == "fast"
    assert drop.template_name == "txt2img_empty"

    defaults = parse_sql("CREATE PRESET fast FOR txt2img_empty AS DEFAULTS;")
    assert defaults.preset_name == "fast"
    assert defaults.template_name == "txt2img_empty"

    create_wf = parse_sql("CREATE TABLE wf_demo AS WORKFLOW '/tmp/wf.json';")
    assert create_wf.table_name == "wf_demo"
    assert create_wf.workflow_path == "/tmp/wf.json"

    drop_wf = parse_sql("DROP TABLE wf_demo;")
    assert drop_wf.table_name == "wf_demo"


def test_create_table_runs_validation_before_register(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf_create.json"
    wf.write_text(
        json.dumps(
            {
                "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}},
                "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "x"}},
            }
        ),
        encoding="utf-8",
    )

    called = {"count": 0}

    def _fake_validate(prompt: dict[str, object]) -> dict[str, object]:
        called["count"] += 1
        assert isinstance(prompt, dict)
        return {"nodes": 2, "edges": 1, "checked_models": [], "checked_assets": []}

    monkeypatch.setattr(engine, "_validate_compiled_prompt", _fake_validate)

    result = engine.execute_sql(
        f"CREATE TABLE demo AS WORKFLOW '{wf}';",
        compile_only=False,
        no_cache=False,
        timeout=30.0,
        statement_index=1,
    )
    assert result["action"] == "create_table"
    assert called["count"] == 1
    assert engine.registry.get("demo") is not None


def test_create_table_runs_asset_upload_preflight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf_create_upload.json"
    wf.write_text(
        json.dumps(
            {
                "1": {"class_type": "LoadImage", "inputs": {"image": "woman.jpg"}},
                "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "x"}},
            }
        ),
        encoding="utf-8",
    )

    seen = {"upload_called": 0}

    def _fake_upload(prompt: dict[str, object], *, timeout: float) -> tuple[dict[str, object], dict[str, object]]:
        seen["upload_called"] += 1
        patched = dict(prompt)
        patched["1"] = dict(patched["1"])  # type: ignore[index]
        patched["1"]["inputs"] = {"image": "assets/woman.jpg"}  # type: ignore[index]
        return patched, {"uploaded_count": 1, "skipped_existing_count": 0, "failed_count": 0}

    monkeypatch.setattr(engine, "_auto_upload_local_assets", _fake_upload)
    monkeypatch.setattr(
        engine,
        "_validate_compiled_prompt",
        lambda prompt: {"nodes": 2, "edges": 1, "checked_models": [], "checked_assets": []},
    )

    result = engine.execute_sql(
        f"CREATE TABLE demo_upload AS WORKFLOW '{wf}';",
        compile_only=False,
        no_cache=False,
        timeout=30.0,
        statement_index=1,
    )
    assert result["action"] == "create_table"
    assert seen["upload_called"] == 1
    assert isinstance(result.get("upload_preflight"), dict)
    assert result["upload_preflight"]["uploaded_count"] == 1


def test_create_table_strict_upload_failure_blocks_register(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf_create_upload_fail.json"
    wf.write_text(
        json.dumps({"1": {"class_type": "LoadImage", "inputs": {"image": "woman.jpg"}}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        engine,
        "_auto_upload_local_assets",
        lambda prompt, timeout: (prompt, {"uploaded_count": 0, "skipped_existing_count": 0, "failed_count": 1, "failed": []}),
    )

    with pytest.raises(SQLEngineError, match="Upload preflight failed; aborting workflow create."):
        engine.execute_sql(
            f"CREATE TABLE demo_upload_fail AS WORKFLOW '{wf}';",
            compile_only=False,
            no_cache=False,
            timeout=30.0,
            statement_index=1,
            upload_mode="strict",
        )

    assert engine.registry.get("demo_upload_fail") is None


def test_create_template_captures_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf_template.json"
    wf.write_text(
        json.dumps(
            {
                "3": {"class_type": "KSampler", "inputs": {"seed": 7, "steps": 15, "cfg": 4}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "hello"}},
                "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "demo"}},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        engine,
        "_validate_compiled_prompt",
        lambda prompt: {"nodes": 3, "edges": 0, "checked_models": [], "checked_assets": []},
    )

    result = engine.execute_sql(
        f"CREATE TEMPLATE demo_template AS WORKFLOW '{wf}';",
        compile_only=False,
        no_cache=False,
        timeout=30.0,
        statement_index=1,
    )
    assert result["action"] == "create_template"
    assert result["kind"] == "template"
    assert isinstance(result.get("default_params"), dict)
    assert result["default_params"]["seed"] == 7
    assert result["default_params"]["steps"] == 15

    stored = engine.registry.get("demo_template")
    assert stored is not None
    assert stored.kind == "template"
    assert isinstance(stored.default_params, dict)
    assert stored.default_params.get("seed") == 7


def test_create_table_imports_meta_from_workflow_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf_with_meta.json"
    wf.write_text(
        json.dumps(
            {
                "meta": {
                    "intent": "image_generation",
                    "capabilities": ["image_to_image"],
                },
                "1": {"class_type": "KSampler", "inputs": {"seed": 3, "steps": 10}},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        engine,
        "_validate_compiled_prompt",
        lambda prompt: {"nodes": 1, "edges": 0, "checked_models": [], "checked_assets": []},
    )
    result = engine.execute_sql(
        f"CREATE TABLE wf_meta AS WORKFLOW '{wf}';",
        compile_only=False,
        no_cache=False,
        timeout=30.0,
        statement_index=1,
    )
    assert result["action"] == "create_table"
    assert result["meta"]["intent"] == "image_generation"
    stored = engine.registry.get("wf_meta")
    assert stored is not None
    assert stored.meta is not None
    assert stored.meta.get("intent") == "image_generation"


def test_set_and_unset_meta_commands(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf_setmeta.json"
    wf.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}), encoding="utf-8")
    engine.registry.create_table("wf_setmeta", wf)

    set_result = engine.execute_sql(
        "SET META FOR wf_setmeta AS '{\"intent\":\"image_generation\",\"quality_profile\":{\"speed\":\"fast\"}}';",
        compile_only=False,
        no_cache=False,
        timeout=30.0,
        statement_index=1,
    )
    assert set_result["action"] == "set_meta"
    assert set_result["meta"]["intent"] == "image_generation"

    describe_result = engine.execute_sql(
        "DESCRIBE WORKFLOW wf_setmeta;",
        compile_only=False,
        no_cache=False,
        timeout=30.0,
        statement_index=2,
    )
    assert describe_result["kind"] == "workflow"
    assert describe_result["meta"]["intent"] == "image_generation"

    unset_result = engine.execute_sql(
        "UNSET META FOR wf_setmeta;",
        compile_only=False,
        no_cache=False,
        timeout=30.0,
        statement_index=3,
    )
    assert unset_result["action"] == "unset_meta"
    assert unset_result["meta"] == {}


def test_show_tables_includes_has_meta_for_registry_entries(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf_show_meta.json"
    wf.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}), encoding="utf-8")
    engine.registry.create_table("wf_show_meta", wf, meta={"intent": "image_generation"})

    class _FakeSchema:
        nodes: dict[str, object] = {}

        @staticmethod
        def list_tables() -> list[dict[str, object]]:
            return []

    engine._load_schema = lambda: _FakeSchema()  # type: ignore[method-assign]
    result = engine.execute_sql(
        "SHOW TABLES workflows;",
        compile_only=False,
        no_cache=False,
        timeout=30.0,
        statement_index=1,
    )
    assert result["action"] == "describe_tables"
    rows = [r for r in result["rows"] if r.get("table") == "wf_show_meta"]
    assert rows
    assert rows[0]["has_meta"] is True


def test_create_table_validation_failure_blocks_register(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = _make_engine(tmp_path)
    wf = tmp_path / "wf_create_fail.json"
    wf.write_text(
        json.dumps({"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}}}),
        encoding="utf-8",
    )

    def _fail_validate(prompt: dict[str, object]) -> dict[str, object]:
        raise SQLEngineError("validation failed", exit_code=2)

    monkeypatch.setattr(engine, "_validate_compiled_prompt", _fail_validate)

    with pytest.raises(SQLEngineError):
        engine.execute_sql(
            f"CREATE TABLE bad AS WORKFLOW '{wf}';",
            compile_only=False,
            no_cache=False,
            timeout=30.0,
            statement_index=1,
        )

    assert engine.registry.get("bad") is None


def test_sql_parser_supports_profile_commands(tmp_path: Path) -> None:
    from comfy_custom.comfysql_runner.sql_parser import parse_sql

    c = parse_sql(
        "CREATE PROFILE portrait WITH lens='50mm (Standard)' AND camera_distance='Medium Close-Up';"
    )
    assert c.profile_name == "portrait"
    assert c.params["lens"] == "50mm (Standard)"

    d = parse_sql("DESCRIBE PROFILE portrait;")
    assert d.profile_name == "portrait"

    drop = parse_sql("DROP PROFILE portrait;")
    assert drop.profile_name == "portrait"


def test_merge_preset_where_precedence(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    engine.preset_registry.upsert(
        template_name="txt2img_empty",
        preset_name="fast",
        params={"seed": 111, "cfg": 8, "steps": 20},
    )
    merged = engine._merge_preset_where(
        table_name="txt2img_empty",
        preset_name="fast",
        where={"seed": 999},
    )
    assert merged["seed"] == 999
    assert merged["cfg"] == 8
    assert merged["steps"] == 20


def test_merge_profile_preset_where_precedence(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    engine.preset_registry.upsert(
        template_name="txt2img_empty",
        preset_name="fast",
        params={"steps": 20, "cfg": 8},
    )
    engine.profile_registry.upsert(
        profile_name="portrait",
        params={"cfg": 10, "lens": "50mm (Standard)"},
    )
    merged = engine._merge_profile_preset_where(
        table_name="txt2img_empty",
        preset_name="fast",
        profile_name="portrait",
        where={"cfg": 7, "prompt": "x"},
    )
    assert merged["cfg"] == 7
    assert merged["steps"] == 20
    assert merged["width"] == 1024


def test_auto_upload_local_assets_maps_assets_and_root_and_skips_existing(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    asset_file = tmp_path / "input" / "assets" / "woman.jpg"
    root_file = tmp_path / "bag-fendi.png"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"a")
    root_file.write_bytes(b"b")

    uploaded_targets: list[tuple[str, str]] = []

    def fake_exists(*, filename: str, subfolder: str, timeout: float) -> bool:
        return filename == "bag-fendi.png" and subfolder == ""

    def fake_upload(
        *,
        local_path: Path,
        remote_filename: str,
        remote_subfolder: str,
        endpoint: str,
        file_field: str,
        timeout: float,
    ) -> None:
        uploaded_targets.append((remote_subfolder, remote_filename))

    engine._remote_input_exists = fake_exists  # type: ignore[method-assign]
    engine._upload_input_file = fake_upload  # type: ignore[method-assign]

    prompt = {
        "1": {"class_type": "LoadImage", "inputs": {"image": str(asset_file)}},
        "2": {"class_type": "LoadImage", "inputs": {"image": str(root_file)}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": str(asset_file)}},
    }
    patched, report = engine._auto_upload_local_assets(prompt, timeout=10.0)

    assert patched["1"]["inputs"]["image"] == "woman.jpg"
    assert patched["2"]["inputs"]["image"] == "bag-fendi.png"
    assert patched["3"]["inputs"]["text"] == str(asset_file)
    assert report["uploaded_count"] == 1
    assert report["skipped_existing_count"] == 1
    assert report["failed_count"] == 0
    assert uploaded_targets == [("", "woman.jpg")]


def test_auto_upload_local_assets_resolves_assets_shorthand(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    data_root = engine.comfy_dir.parent
    woman_file = data_root / "input" / "assets" / "woman.jpg"
    woman_file.parent.mkdir(parents=True, exist_ok=True)
    woman_file.write_bytes(b"a")

    uploaded_targets: list[tuple[str, str]] = []

    def fake_exists(*, filename: str, subfolder: str, timeout: float) -> bool:
        return False

    def fake_upload(
        *,
        local_path: Path,
        remote_filename: str,
        remote_subfolder: str,
        endpoint: str,
        file_field: str,
        timeout: float,
    ) -> None:
        uploaded_targets.append((remote_subfolder, remote_filename))

    engine._remote_input_exists = fake_exists  # type: ignore[method-assign]
    engine._upload_input_file = fake_upload  # type: ignore[method-assign]

    prompt = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "assets/woman.jpg"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "woman.jpg"}},
    }
    patched, report = engine._auto_upload_local_assets(prompt, timeout=10.0)

    assert patched["1"]["inputs"]["image"] == "woman.jpg"
    assert patched["2"]["inputs"]["image"] == "woman.jpg"
    assert report["uploaded_count"] == 2
    assert report["failed_count"] == 0
    assert uploaded_targets == [("", "woman.jpg")]


def test_auto_upload_local_assets_records_failures(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    image_file = tmp_path / "x.png"
    image_file.write_bytes(b"img")

    def fake_exists(*, filename: str, subfolder: str, timeout: float) -> bool:
        return False

    def fake_upload(
        *,
        local_path: Path,
        remote_filename: str,
        remote_subfolder: str,
        endpoint: str,
        file_field: str,
        timeout: float,
    ) -> None:
        raise SQLEngineError("boom", exit_code=4)

    engine._remote_input_exists = fake_exists  # type: ignore[method-assign]
    engine._upload_input_file = fake_upload  # type: ignore[method-assign]

    prompt = {
        "1": {"class_type": "LoadImage", "inputs": {"image": str(image_file)}},
    }
    patched, report = engine._auto_upload_local_assets(prompt, timeout=10.0)

    assert patched["1"]["inputs"]["image"] == str(image_file)
    assert report["uploaded_count"] == 0
    assert report["skipped_existing_count"] == 0
    assert report["failed_count"] == 1
    assert report["failed"][0]["remote_path"] == "x.png"


def test_normalize_asset_binding_preserves_non_assets_prefix(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    value = engine._normalize_asset_binding_value(
        class_type="LoadImage",
        input_name="image",
        value="woman.jpg",
    )
    assert value == "woman.jpg"


def test_merge_preset_applies_cinematic_fields_to_prompt_and_size(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    engine.preset_registry.upsert(
        template_name="txt2img_empty",
        preset_name="preset1",
        params={
            "lens": "50mm (Standard)",
            "camera_distance": "Medium Close-Up",
            "camera_angle": "Low Angle",
            "lighting_direction": "front, side, back, top",
            "lighting_type": "natural light",
            "lighting_quality": "soft",
            "lighting_time": "golden hour",
        },
    )

    merged = engine._merge_preset_where(
        table_name="txt2img_empty",
        preset_name="preset1",
        where={"prompt": "a cinematic portrait of a woman"},
    )

    assert merged["width"] == 1024
    assert merged["height"] == 1024
    assert "50mm" in merged["prompt"]
    assert "Medium Close-Up" in merged["prompt"]
    assert "Low Angle" in merged["prompt"]
    assert "lighting direction front, side, back, top" in merged["prompt"]


def test_merge_preset_does_not_override_explicit_size(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    merged = engine._apply_cinematic_preset_fields(
        {
            "prompt": "x",
            "lens": "85mm (Portrait)",
            "width": 640,
            "height": 640,
        }
    )
    assert merged["width"] == 640
    assert merged["height"] == 640
