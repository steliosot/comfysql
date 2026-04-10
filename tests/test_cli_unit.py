from __future__ import annotations

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


def test_cmd_stop_not_running(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "read_state", lambda: None)
    monkeypatch.setattr(cli, "is_server_healthy", lambda host, port, timeout=1.5: False)
    args = type("Args", (), {"host": "127.0.0.1", "port": 8188, "timeout": 1.0, "force": False})()
    rc = cli.cmd_stop(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "server_not_running" in out


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

    monkeypatch.setattr(cli, "get_comfy_files_dir", lambda: Path("/tmp/comfy"))
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
