from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from comfy_custom import cli


def _prepare_workspace(tmp_path: Path) -> None:
    (tmp_path / "comfy_files").mkdir(parents=True, exist_ok=True)
    (tmp_path / "comfy_files" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "comfy-custom" / ".state").mkdir(parents=True, exist_ok=True)


def test_state_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_workspace(tmp_path)
    monkeypatch.setattr(cli, "_find_workspace_root", lambda: tmp_path)

    state = cli.RuntimeState(pid=1234, host="127.0.0.1", port=8188, log_path="/tmp/server.log", started_at=1.5)
    cli.write_state(state)

    loaded = cli.read_state()
    assert loaded is not None
    assert loaded.pid == 1234
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 8188


def test_build_connection_settings_resolves_host_alias_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_workspace(tmp_path)
    monkeypatch.setattr(cli, "_find_workspace_root", lambda: tmp_path)
    monkeypatch.delenv("COMFY_URL", raising=False)
    cfg = {
        "version": 1,
        "default_server": "localhost",
        "servers": {
            "localhost": {"url": "http://127.0.0.1:8188"},
            "remote": {"url": "http://34.132.147.127:80"},
        },
    }
    (tmp_path / "comfysql.json").write_text(json.dumps(cfg), encoding="utf-8")
    args = argparse.Namespace(server="", host="remote", port=8188, config=None)

    settings = cli._build_connection_settings(args)
    assert settings.host == "34.132.147.127"
    assert settings.port == 80
    assert settings.scheme == "http"


def test_resolve_config_path_prefers_comfysql_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_workspace(tmp_path)
    primary = tmp_path / "comfysql.json"
    legacy = tmp_path / "comfy-agent.json"
    primary.write_text("{}", encoding="utf-8")
    legacy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "_find_workspace_root", lambda: tmp_path)
    args = argparse.Namespace(config=None)
    path = cli._resolve_config_path(args)
    assert path == primary.resolve()


def test_resolve_config_path_falls_back_to_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_workspace(tmp_path)
    legacy = tmp_path / "comfy-agent.json"
    legacy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "_find_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "_LEGACY_CONFIG_HINT_SHOWN", False)
    args = argparse.Namespace(config=None)
    path = cli._resolve_config_path(args)
    assert path == legacy.resolve()


def test_ensure_server_running_starts_when_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = cli.RuntimeState(pid=99, host="127.0.0.1", port=8188, log_path="/tmp/log", started_at=0.0)
    monkeypatch.setattr(cli, "is_server_healthy", lambda host, port, timeout=2.0: False)
    monkeypatch.setattr(cli, "start_server", lambda host, port, timeout=cli.DEFAULT_START_TIMEOUT: expected)

    state = cli.ensure_server_running("127.0.0.1", 8188)
    assert state.pid == 99


def test_validate_api_prompt_rejects_bad_shape() -> None:
    with pytest.raises(cli.CliError):
        cli.validate_api_prompt({"1": {"inputs": {}}})


def test_parse_ws_event_progress_and_executed() -> None:
    prompt_id = "pid-1"

    progress_raw = json.dumps(
        {"type": "progress", "data": {"value": 1, "max": 4, "prompt_id": prompt_id, "node": "3"}}
    )
    event, text = cli.parse_ws_event(progress_raw, prompt_id=prompt_id)
    assert event == "progress"
    assert text is not None and "25%" in text

    executed_raw = json.dumps({"type": "executing", "data": {"prompt_id": prompt_id, "node": None}})
    event2, text2 = cli.parse_ws_event(executed_raw, prompt_id=prompt_id)
    assert event2 == "executed"
    assert text2 == "executed"


def test_apply_no_cache_mutation_updates_seed() -> None:
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 5, "steps": 20}},
        "4": {"class_type": "Other", "inputs": {"value": 1}},
    }
    old_seed = workflow["3"]["inputs"]["seed"]
    mutated = cli.apply_no_cache_mutation(workflow)
    assert mutated == 1
    assert workflow["3"]["inputs"]["seed"] != old_seed


def test_cmd_status_stopped(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "read_state", lambda: None)
    monkeypatch.setattr(cli, "is_server_healthy", lambda host, port, timeout=1.5: False)
    args = type("Args", (), {"host": "127.0.0.1", "port": 8188})()
    rc = cli.cmd_status(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "status=stopped" in out


def test_parser_does_not_include_stop_restart() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["stop"])
    with pytest.raises(SystemExit):
        parser.parse_args(["restart"])


def test_confirm_sql_if_needed_handles_non_interactive_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(EOFError()))
    with pytest.raises(cli.CliError, match="Re-run with -y"):
        cli._confirm_sql_if_needed("DROP TABLE demo;", yes=False)


def test_is_destructive_sql_detects_core_mutating_forms() -> None:
    assert cli._is_destructive_sql("CREATE TABLE demo AS WORKFLOW '/tmp/x.json';") is True
    assert cli._is_destructive_sql("CREATE CHARACTER char_matt WITH image='matt.png';") is True
    assert cli._is_destructive_sql("CREATE SLOT subject FOR wf AS CHARACTER BINDING input_image;") is True
    assert cli._is_destructive_sql("SET META FOR demo AS '{\"intent\":\"image_generation\"}';") is True
    assert cli._is_destructive_sql("UNSET META FOR demo;") is True
    assert cli._is_destructive_sql("RUN QUERY quick;") is True
    assert cli._is_destructive_sql("SELECT image FROM txt2img_empty_latent WHERE seed=1;") is False


def test_execute_sql_statement_confirms_report_inner_sql(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def _fake_confirm(*, sql_text: str, yes: bool) -> None:
        seen["sql_text"] = sql_text
        seen["yes"] = yes

    def _fake_report(**kwargs):
        seen["report_sql"] = kwargs["sql_text"]
        return 0

    monkeypatch.setattr(cli, "_confirm_sql_if_needed", _fake_confirm)
    monkeypatch.setattr(cli, "_run_sql_report", _fake_report)
    args = type("Args", (), {"title": "", "yes": False})()
    cli._execute_sql_statement(
        engine=object(),  # type: ignore[arg-type]
        sql_text=f"REPORT CREATE PROFILE p1 WITH width=512 TO '{tmp_path / 'r.md'}';",
        args=args,
        statement_index=1,
    )
    assert str(seen.get("sql_text", "")).startswith("CREATE PROFILE")
    assert str(seen.get("report_sql", "")).startswith("CREATE PROFILE")


def test_error_hint_for_non_interactive_confirmation() -> None:
    hint = cli._error_hint_for_message("Confirmation required for state-changing SQL in non-interactive mode.")
    assert hint is not None
    assert "-y" in hint


def test_resolve_download_url_supports_relative_view_path() -> None:
    assert (
        cli._resolve_download_url("view?filename=x.png&type=output", host="127.0.0.1", port=8188)
        == "http://127.0.0.1:8188/view?filename=x.png&type=output"
    )
    assert (
        cli._resolve_download_url("/view?filename=x.png&type=output", host="127.0.0.1", port=8188)
        == "http://127.0.0.1:8188/view?filename=x.png&type=output"
    )


def test_cmd_download_writes_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b"abc123"

    seen: dict[str, str] = {}

    def _fake_open(url: str, **kwargs):
        seen["url"] = url
        return _Resp()

    monkeypatch.setattr(cli, "urlopen_with_auth_fallback", _fake_open)
    out_path = tmp_path / "x.bin"
    args = argparse.Namespace(
        url="view?filename=x.png&type=output",
        output=str(out_path),
        host="127.0.0.1",
        port=8188,
        timeout=5.0,
    )
    rc = cli.cmd_download(args)
    assert rc == 0
    assert out_path.read_bytes() == b"abc123"
    assert seen["url"].startswith("http://127.0.0.1:8188/view?")
    out = capsys.readouterr().out
    assert "downloaded path=" in out


def test_cmd_bind_character_upserts_binding(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class _Engine:
        def _auto_upload_local_assets(self, prompt, timeout: float):
            return prompt, {"uploaded_count": 0, "skipped_existing_count": 0, "failed_count": 0}

        def upsert_character_binding(self, **kwargs):
            return type(
                "Spec",
                (),
                {
                    "workflow_table": kwargs["workflow_table"],
                    "character_name": kwargs["character_name"],
                    "binding_key": kwargs["binding_key"],
                    "binding_value": kwargs["binding_value"],
                },
            )()

    monkeypatch.setattr(cli, "_build_sql_engine", lambda args: _Engine())
    args = argparse.Namespace(
        workflow="img2img_controlnet",
        character="char_nick",
        image="nick.jpg.avif",
        binding="input_image",
        upload=False,
        timeout=10.0,
        yes=True,
    )
    rc = cli.cmd_bind_character(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "character_bound action=upserted" in out


def test_cmd_bind_character_upserts_with_upload(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class _Engine:
        def _auto_upload_local_assets(self, prompt, timeout: float):
            return {"1": {"class_type": "LoadImage", "inputs": {"image": "nick.jpg.avif"}}}, {
                "uploaded_count": 1,
                "skipped_existing_count": 0,
                "failed_count": 0,
            }

        def upsert_character_binding(self, **kwargs):
            return type(
                "Spec",
                (),
                {
                    "workflow_table": kwargs["workflow_table"],
                    "character_name": kwargs["character_name"],
                    "binding_key": kwargs["binding_key"],
                    "binding_value": kwargs["binding_value"],
                },
            )()

    monkeypatch.setattr(cli, "_build_sql_engine", lambda args: _Engine())
    args = argparse.Namespace(
        workflow="img2img_controlnet",
        character="char_nick",
        image="nick.jpg.avif",
        binding="input_image",
        upload=True,
        timeout=10.0,
        yes=True,
    )
    rc = cli.cmd_bind_character(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "character_bound action=upserted" in out
    assert "upload_preflight uploaded=1" in out


def test_cmd_sql_report_writes_markdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    image_path = tmp_path / "out.png"
    image_path.write_bytes(b"png")

    class _Engine:
        def execute_sql(self, **kwargs):
            return {
                "action": "select",
                "api_prompt_path": str(tmp_path / "api_prompt.json"),
                "downloaded_outputs": [str(image_path)],
            }

    monkeypatch.setattr(cli, "_build_sql_engine", lambda args: _Engine())
    report_path = tmp_path / "report.md"
    args = argparse.Namespace(
        sql=(
            "SELECT image FROM img2img_reference USING default_run CHARACTER char_matt "
            "PROFILE mediumshot_natural WHERE prompt='x' AND seed=1;"
        ),
        sql_file=None,
        host="127.0.0.1",
        port=8188,
        timeout=10.0,
        no_cache=False,
        compile_only=False,
        upload_mode="strict",
        download_output=True,
        download_dir=None,
        report=str(report_path),
        title="My Report",
        image=[],
    )
    rc = cli.cmd_sql_report(args)
    assert rc == 0
    text = report_path.read_text(encoding="utf-8")
    assert "# My Report" in text
    assert "## SQL" in text
    assert "img2img_reference" in text
    assert "char_matt" in text
    assert "Character: `char_matt`" in text
    assert "mediumshot_natural" in text
    assert "![out.png](" in text
    out = capsys.readouterr().out
    assert "report_written path=" in out


def test_cmd_sql_report_rejects_multiple_statements(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_sql_engine", lambda args: object())
    args = argparse.Namespace(
        sql="SHOW TABLES; SHOW PROFILES;",
        sql_file=None,
        host="127.0.0.1",
        port=8188,
        timeout=10.0,
        no_cache=False,
        compile_only=False,
        upload_mode="strict",
        download_output=True,
        download_dir=None,
        report=None,
        title=None,
        image=[],
    )
    with pytest.raises(cli.CliError, match="exactly one SQL statement"):
        cli.cmd_sql_report(args)


def test_looks_like_link() -> None:
    assert cli._looks_like_link(["1", 0]) is True
    assert cli._looks_like_link([1, 0]) is True
    assert cli._looks_like_link(["1", "0"]) is False
    assert cli._looks_like_link({"a": 1}) is False


def test_is_ui_workflow_json() -> None:
    assert cli._is_ui_workflow_json({"nodes": [], "links": []}) is True
    assert cli._is_ui_workflow_json({"1": {"class_type": "A", "inputs": {}}}) is False


def test_graph_from_api_prompt_builds_nodes_and_edges() -> None:
    class _NodeType:
        def __init__(self):
            self.output_map = {"out": 0}

    class _Catalog:
        def __init__(self):
            self.node_types = {"A": _NodeType(), "B": _NodeType()}

    catalog = _Catalog()
    workflow = {
        "1": {"class_type": "A", "inputs": {"seed": 5}},
        "2": {"class_type": "B", "inputs": {"inp": ["1", 0]}},
    }
    graph = cli._graph_from_api_prompt(workflow, catalog)
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.source_node == "1"
    assert edge.target_node == "2"
    assert edge.target_input == "inp"


def test_split_sql_statements_handles_multiple() -> None:
    sql = "SELECT image FROM img2img_process WHERE prompt='a'; SELECT image FROM img2img_process WHERE seed=2;"
    statements = cli._split_sql_statements(sql)
    assert len(statements) == 2
    assert statements[0].strip().endswith(";")
    assert "prompt='a'" in statements[0]


def test_split_sql_statements_handles_escaped_quotes() -> None:
    sql = "SELECT image FROM txt2img_empty_latent WHERE prompt='it''s TO good'; SELECT image FROM txt2img_empty_latent WHERE seed=2;"
    statements = cli._split_sql_statements(sql)
    assert len(statements) == 2
    assert "it''s TO good" in statements[0]


def test_is_complete_sql_statement_supports_optional_semicolon() -> None:
    assert cli._is_complete_sql_statement("SHOW TABLES") is True
    assert cli._is_complete_sql_statement("SHOW TABLES;") is True
    assert cli._is_complete_sql_statement("SELECT") is False


def test_should_auto_execute_without_semicolon_only_for_single_line() -> None:
    assert cli._should_auto_execute_without_semicolon(sql_text="SHOW TABLES", buffered_line_count=1) is True
    assert cli._should_auto_execute_without_semicolon(sql_text="SHOW TABLES", buffered_line_count=2) is False
    assert (
        cli._should_auto_execute_without_semicolon(
            sql_text="CREATE PROFILE starter_portrait_v1 WITH width=1024",
            buffered_line_count=2,
        )
        is False
    )


def test_parse_report_sql_supports_optional_semicolon() -> None:
    parsed = cli._parse_report_sql(
        "REPORT SELECT image FROM img2img_controlnet USING char_nick PROFILE goldenhour_backlight "
        "WHERE prompt='sunset street' AND seed=42 TO './examples/out.md'"
    )
    assert parsed is not None
    inner_sql, report_path = parsed
    assert "SELECT image FROM img2img_controlnet" in inner_sql
    assert report_path == "./examples/out.md"

    parsed2 = cli._parse_report_sql(
        "REPORT SELECT image FROM img2img_controlnet USING char_nick PROFILE goldenhour_backlight "
        "WHERE prompt='sunset street' AND seed=42 TO \"./examples/out2.md\";"
    )
    assert parsed2 is not None
    inner_sql2, report_path2 = parsed2
    assert "USING char_nick" in inner_sql2
    assert report_path2 == "./examples/out2.md"


def test_parse_report_sql_handles_to_inside_string_literal() -> None:
    parsed = cli._parse_report_sql(
        "REPORT SELECT image FROM txt2img_empty_latent "
        "WHERE prompt='go TO London at sunset' AND seed=42 TO './examples/to_test.md';"
    )
    assert parsed is not None
    inner_sql, report_path = parsed
    assert "go TO London" in inner_sql
    assert report_path == "./examples/to_test.md"


def test_main_json_error_envelope_and_normalized_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(_args):
        raise cli.CliError("Validation failed fetching node catalog: timeout", exit_code=3)

    monkeypatch.setattr(cli, "cmd_doctor", _boom)
    parser = cli.build_parser()
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    monkeypatch.setattr(cli, "_apply_connection_settings", lambda _args: None)
    rc = cli.main(["doctor", "--output", "json"])
    assert rc == cli.EXIT_VALIDATION
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["status"] == "error"
    assert payload["exit_code"] == cli.EXIT_VALIDATION


def test_parser_doctor_full_and_output_flags() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["doctor", "--full", "--output", "json"])
    assert args.full is True
    assert args.output == "json"


def test_execute_sql_statement_routes_report_sql(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def _fake_report(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "_run_sql_report", _fake_report)

    args = type(
        "Args",
        (),
        {
            "title": "",
            "yes": False,
        },
    )()
    engine = object()
    cli._execute_sql_statement(
        engine=engine,  # type: ignore[arg-type]
        sql_text=(
            "REPORT SELECT image FROM img2img_controlnet USING char_nick PROFILE goldenhour_backlight "
            f"WHERE prompt='x' AND seed=1 TO '{tmp_path / 'from_terminal.md'}';"
        ),
        args=args,
        statement_index=1,
    )
    assert seen["engine"] is engine
    assert "SELECT image FROM img2img_controlnet" in str(seen["sql_text"])
    assert Path(str(seen["report_path"])).name == "from_terminal.md"


def test_cmd_sql_uses_sql_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sql_file = tmp_path / "q.sql"
    sql_file.write_text(
        "SELECT image FROM img2img_process WHERE prompt='cat';\n"
        "SELECT image FROM img2img_process WHERE seed=5;",
        encoding="utf-8",
    )

    seen: list[tuple[int, str]] = []

    monkeypatch.setattr(cli, "_build_sql_engine", lambda args: object())

    def _fake_exec(engine, sql_text, args, statement_index):
        seen.append((statement_index, sql_text.strip()))

    monkeypatch.setattr(cli, "_execute_sql_statement", _fake_exec)
    args = type(
        "Args",
        (),
        {
            "sql": None,
            "sql_file": str(sql_file),
            "host": "127.0.0.1",
            "port": 8188,
            "timeout": 10.0,
            "no_cache": False,
            "compile_only": False,
        },
    )()

    rc = cli.cmd_sql(args)
    assert rc == 0
    assert len(seen) == 2
    assert seen[0][0] == 1
    assert "prompt='cat'" in seen[0][1]
    assert seen[1][0] == 2


def test_cmd_sql_prefers_terminal_when_no_sql(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called = {"ok": False}

    monkeypatch.setattr(cli, "_build_sql_engine", lambda args: object())

    def _fake_terminal(args, engine):
        called["ok"] = True
        return 0

    monkeypatch.setattr(cli, "_run_sql_terminal", _fake_terminal)
    args = type(
        "Args",
        (),
        {
            "sql": None,
            "sql_file": None,
            "host": "127.0.0.1",
            "port": 8188,
            "timeout": 10.0,
            "no_cache": False,
            "compile_only": False,
        },
    )()

    rc = cli.cmd_sql(args)
    assert rc == 0
    assert called["ok"] is True


def test_cmd_sql_inline_sql_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_build_sql_engine", lambda args: object())
    seen: list[str] = []

    def _fake_exec(engine, sql_text, args, statement_index):
        seen.append(sql_text)

    monkeypatch.setattr(cli, "_execute_sql_statement", _fake_exec)
    args = type(
        "Args",
        (),
        {
            "sql": "SELECT image FROM img2img_process WHERE seed=5;",
            "sql_file": None,
            "host": "127.0.0.1",
            "port": 8188,
            "timeout": 10.0,
            "no_cache": False,
            "compile_only": False,
        },
    )()

    rc = cli.cmd_sql(args)
    assert rc == 0
    assert len(seen) == 1


def test_collect_asset_files_all_prefers_assets_and_includes_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "repo"
    assets_dir = workspace / "input" / "assets"
    input_dir = workspace / "input"
    assets_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "a.png").write_bytes(b"a")
    (input_dir / "a.png").write_bytes(b"legacy-a")
    (input_dir / "b.png").write_bytes(b"b")
    (input_dir / ".DS_Store").write_text("x", encoding="utf-8")

    monkeypatch.setattr(cli, "_find_workspace_root", lambda: workspace)
    files = cli._collect_asset_files(source=None, all_assets=True)
    names = [p.name for p in files]
    assert "a.png" in names
    assert "b.png" in names
    assert ".DS_Store" not in names
    assert any(p == (assets_dir / "a.png").resolve() for p in files)
    assert all(p != (input_dir / "a.png").resolve() for p in files)


def test_collect_asset_files_all_supports_legacy_input_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "repo"
    input_dir = workspace / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "legacy.jpg").write_bytes(b"x")

    monkeypatch.setattr(cli, "_find_workspace_root", lambda: workspace)
    files = cli._collect_asset_files(source=None, all_assets=True)
    assert files == [(input_dir / "legacy.jpg").resolve()]


def test_cmd_pull_success(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    class _Report:
        total = 3
        need_download_before = 1
        existing_before = 2
        copied = 1
        skipped_exists = 2
        failed = 0
        bytes_copied = 100
        dry_run = False

    monkeypatch.setattr(cli, "get_comfy_data_dir", lambda: Path("/tmp/comfy"))
    monkeypatch.setattr(cli, "get_state_dir", lambda: Path("/tmp/state"))
    monkeypatch.setattr(cli, "execute_pull", lambda **kwargs: _Report())
    args = type(
        "Args",
        (),
        {
            "dropbox_url": "https://www.dropbox.com/s/abc/shared?dl=0",
            "manifest": "/tmp/manifest.json",
            "yes": True,
            "dry_run": False,
            "host": "127.0.0.1",
            "port": 8188,
        },
    )()
    rc = cli.cmd_pull(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "pull_done" in out


def test_cmd_pull_falls_back_to_workspace_when_data_dir_invalid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Report:
        copied = 0
        skipped_exists = 0
        failed = 0
        bytes_copied = 0
        dry_run = True

    monkeypatch.setattr(cli, "_find_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "get_comfy_data_dir", lambda: (_ for _ in ()).throw(cli.CliError("bad")))
    monkeypatch.setattr(cli, "get_state_dir", lambda: tmp_path / ".state")
    seen: dict[str, Path] = {}

    def _fake_execute_pull(**kwargs):
        seen["models_dir"] = kwargs["models_dir"]
        return _Report()

    monkeypatch.setattr(cli, "execute_pull", _fake_execute_pull)
    args = type("Args", (), {"config": None, "yes": True, "dry_run": True})()
    rc = cli.cmd_pull(args)
    assert rc == 0
    assert seen["models_dir"] == (tmp_path / "models").resolve()


def test_build_parser_submit_validate_support_server_then_workflow() -> None:
    parser = cli.build_parser()
    submit_args = parser.parse_args(["submit", "remote", "wf.json"])
    assert submit_args.command == "submit"
    assert submit_args.server_or_workflow == "remote"
    assert submit_args.workflow == "wf.json"

    validate_args = parser.parse_args(["validate", "remote", "wf.json"])
    assert validate_args.command == "validate"
    assert validate_args.server_or_workflow == "remote"
    assert validate_args.workflow == "wf.json"


def test_build_parser_submit_validate_support_workflow_only() -> None:
    parser = cli.build_parser()
    submit_args = parser.parse_args(["submit", "wf.json"])
    assert submit_args.server_or_workflow == "wf.json"
    assert submit_args.workflow is None

    validate_args = parser.parse_args(["validate", "wf.json"])
    assert validate_args.server_or_workflow == "wf.json"
    assert validate_args.workflow is None


def test_build_parser_sql_report_supports_no_download_output_flag() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["sql-report", "--sql", "SHOW TABLES;", "--no-download-output"])
    assert args.download_output is False


def test_cmd_start_warns_when_no_models(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    state = cli.RuntimeState(pid=123, host="127.0.0.1", port=8188, log_path="/tmp/server.log", started_at=1.0)
    monkeypatch.setattr(cli, "start_server", lambda host, port, timeout=cli.DEFAULT_START_TIMEOUT: state)
    monkeypatch.setattr(cli, "get_comfy_data_dir", lambda: Path("/tmp/data"))
    monkeypatch.setattr(cli, "_has_synced_models", lambda _path: False)
    args = type("Args", (), {"host": "127.0.0.1", "port": 8188, "start_timeout": 1.0})()
    rc = cli.cmd_start(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "server_started" in out
    assert "no synced models found" in out


def test_error_hint_for_message_alias_issue() -> None:
    hint = cli._error_hint_for_message("Unknown server alias 'remotee'. Available: remote")
    assert hint is not None
    assert "config init" in hint


def test_error_hint_for_message_sql_parse() -> None:
    hint = cli._error_hint_for_message("SQL parse failed: Unsupported SQL statement")
    assert hint is not None
    assert "EXPLAIN SELECT" in hint


def test_print_error_with_hint_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_error_with_hint("Unknown server alias 'x'", to_stderr=True)
    err = capsys.readouterr().err
    assert "Unknown server alias" in err
    assert "hint:" in err


def test_render_sql_result_plain_meta_actions(capsys: pytest.CaptureFixture[str]) -> None:
    cli._render_sql_result({"action": "set_meta", "table": "img2img_reference"})
    cli._render_sql_result({"action": "unset_meta", "table": "img2img_reference"})
    out = capsys.readouterr().out
    assert "meta_set table=img2img_reference" in out
    assert "meta_unset table=img2img_reference" in out


def test_render_sql_result_styled_meta_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeUI:
        styled = True

        def __init__(self) -> None:
            self.lines: list[str] = []

        def line(self, text: str) -> None:
            self.lines.append(text)

        def print_json(self, _payload: object) -> None:
            self.lines.append("json")

        def print_table(self, _title: str, _headers: list[str], _rows: list[list[str]]) -> None:
            self.lines.append("table")

    fake = _FakeUI()
    monkeypatch.setattr(cli, "_ui", lambda: fake)
    cli._render_sql_result({"action": "set_meta", "table": "img2img_reference"})
    assert any("set_meta" in line for line in fake.lines)


def test_render_sql_result_plain_show_tables_all_collapses_nodes(capsys: pytest.CaptureFixture[str]) -> None:
    rows: list[dict[str, object]] = [
        {"kind": "workflow", "table": "txt2img_empty_latent", "intent": "image_generation", "signature": "text_to_image"}
    ]
    rows.extend({"kind": "node", "table": f"Node{i}", "category": "core"} for i in range(20))
    cli._render_sql_result({"action": "describe_tables", "table_filter": "all", "rows": rows})
    out = capsys.readouterr().out
    assert "tables_total=21" in out
    assert "Node0" in out
    assert "Node11" in out
    assert "Node12" not in out
    assert "SHOW TABLES nodes;" in out


def test_render_sql_result_styled_show_tables_all_collapses_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeUI:
        styled = True

        def __init__(self) -> None:
            self.lines: list[str] = []
            self.tables: list[tuple[str, list[list[str]]]] = []

        def line(self, text: str) -> None:
            self.lines.append(text)

        def print_json(self, _payload: object) -> None:
            self.lines.append("json")

        def print_table(self, title: str, _headers: list[str], rows: list[list[str]]) -> None:
            self.tables.append((title, rows))

    fake = _FakeUI()
    monkeypatch.setattr(cli, "_ui", lambda: fake)
    rows: list[dict[str, object]] = [
        {"kind": "workflow", "table": "txt2img_empty_latent", "intent": "image_generation", "signature": "text_to_image"}
    ]
    rows.extend({"kind": "node", "table": f"Node{i}", "category": "core"} for i in range(20))
    cli._render_sql_result({"action": "describe_tables", "table_filter": "all", "rows": rows})
    node_tables = [r for (title, r) in fake.tables if title == "NODES"]
    assert node_tables
    assert len(node_tables[0]) == 12
    assert any("SHOW TABLES nodes;" in line for line in fake.lines)


def test_render_sql_result_plain_character_object_actions(capsys: pytest.CaptureFixture[str]) -> None:
    cli._render_sql_result(
        {
            "action": "show_characters",
            "rows": [{"name": "char_matt", "workflow_count": 2, "binding_count": 3}],
        }
    )
    cli._render_sql_result(
        {
            "action": "show_objects",
            "rows": [{"name": "obj_hat", "workflow_count": 1, "binding_count": 1}],
        }
    )
    cli._render_sql_result({"action": "describe_character", "name": "char_matt", "binding_count": 1, "bindings": []})
    out = capsys.readouterr().out
    assert "characters_count=1" in out
    assert "objects_count=1" in out
    assert "char_matt" in out
    assert "obj_hat" in out


def test_sql_terminal_hints_include_character_object_commands() -> None:
    assert "SHOW CHARACTERS" in cli.SQL_TERMINAL_HINTS
    assert "SHOW OBJECTS" in cli.SQL_TERMINAL_HINTS
    assert "DESCRIBE CHARACTER" in cli.SQL_TERMINAL_HINTS
    assert "DESCRIBE OBJECT" in cli.SQL_TERMINAL_HINTS
