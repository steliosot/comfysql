from __future__ import annotations

import atexit
import argparse
import copy
import json
import os
import random
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import websocket
from comfy_custom.sql_engine import LocalComfySQLEngine, SQLEngineError
from comfy_custom.terminal_ui import TerminalUI


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8188
DEFAULT_START_TIMEOUT = 300.0
DEFAULT_SUBMIT_TIMEOUT = 600.0
DEFAULT_CONFIG_FILE = "comfy-agent.json"
_UI: TerminalUI | None = None
_REQUEST_HEADERS: dict[str, str] = {}
_HTTP_SCHEME = "http"
_WS_SCHEME = "ws"
_TARGET_REMOTE = False


class CliError(Exception):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class RuntimeState:
    pid: int
    host: str
    port: int
    log_path: str
    started_at: float


@dataclass
class ConnectionSettings:
    scheme: str
    host: str
    port: int
    headers: dict[str, str]
    remote: bool
    start_timeout: float | None = None
    submit_timeout: float | None = None


def log(message: str) -> None:
    print(f"[comfy-agent] {message}", flush=True)


def _is_local_host(host: str) -> bool:
    value = (host or "").strip().lower()
    return value in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _http_url(host: str, port: int, path: str) -> str:
    return f"{_HTTP_SCHEME}://{host}:{port}{path}"


def _ws_url(host: str, port: int, path: str) -> str:
    return f"{_WS_SCHEME}://{host}:{port}{path}"


def _request_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(_REQUEST_HEADERS)
    if extra:
        headers.update(extra)
    return headers


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CliError(f"Invalid config JSON at {path}: {exc}", exit_code=2) from exc
    if not isinstance(data, dict):
        raise CliError(f"Config file must be a JSON object: {path}", exit_code=2)
    return data


def _resolve_config_path(args: argparse.Namespace) -> Path:
    raw = getattr(args, "config", None)
    if raw:
        return Path(raw).expanduser().resolve()
    return (_find_workspace_root() / DEFAULT_CONFIG_FILE).resolve()


def _parse_url(raw_url: str) -> tuple[str, str, int]:
    parsed = parse.urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise CliError("COMFY_URL/config server.url must start with http:// or https://", exit_code=2)
    if not parsed.hostname:
        raise CliError("COMFY_URL/config server.url is missing hostname", exit_code=2)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname, int(port)


def _build_connection_settings(args: argparse.Namespace) -> ConnectionSettings:
    config_path = _resolve_config_path(args)
    config_payload: dict[str, Any] = {}
    if config_path.exists():
        config_payload = _load_json_file(config_path)

    server_cfg = config_payload.get("server", {}) if isinstance(config_payload.get("server"), dict) else {}
    servers_cfg = config_payload.get("servers", {}) if isinstance(config_payload.get("servers"), dict) else {}
    default_server_name = str(config_payload.get("default_server", "")).strip()
    requested_server_name = str(getattr(args, "server", "") or "").strip()

    selected_server_cfg: dict[str, Any] = {}
    if requested_server_name:
        if not servers_cfg:
            raise CliError(
                f"Server alias '{requested_server_name}' requested, but config has no 'servers' map.",
                exit_code=2,
            )
        raw = servers_cfg.get(requested_server_name)
        if not isinstance(raw, dict):
            available = ", ".join(sorted(servers_cfg.keys())) or "(none)"
            raise CliError(
                f"Unknown server alias '{requested_server_name}'. Available: {available}",
                exit_code=2,
            )
        selected_server_cfg = raw
    elif default_server_name and isinstance(servers_cfg.get(default_server_name), dict):
        selected_server_cfg = servers_cfg[default_server_name]
    elif isinstance(server_cfg, dict):
        selected_server_cfg = server_cfg

    auth_cfg = selected_server_cfg.get("auth", {}) if isinstance(selected_server_cfg.get("auth"), dict) else {}
    timeout_cfg = selected_server_cfg.get("timeout", {}) if isinstance(selected_server_cfg.get("timeout"), dict) else {}

    url_from_env = os.environ.get("COMFY_URL")
    url_from_cfg = selected_server_cfg.get("url")
    resolved_url = str(url_from_env or url_from_cfg or "").strip()

    cli_host = str(getattr(args, "host", DEFAULT_HOST))
    cli_port = int(getattr(args, "port", DEFAULT_PORT))
    using_cli_defaults = cli_host == DEFAULT_HOST and cli_port == DEFAULT_PORT

    scheme = _HTTP_SCHEME
    host = cli_host
    port = cli_port

    if resolved_url and using_cli_defaults:
        parsed_scheme, parsed_host, parsed_port = _parse_url(resolved_url)
        scheme, host, port = parsed_scheme, parsed_host, parsed_port

    token = str(os.environ.get("COMFY_AUTH_HEADER") or auth_cfg.get("token") or "").strip()
    header_name = str(os.environ.get("COMFY_AUTH_HEADER_NAME") or auth_cfg.get("header_name") or "Authorization").strip()
    auth_scheme = str(os.environ.get("COMFY_AUTH_SCHEME") or auth_cfg.get("scheme") or "Bearer").strip()
    headers: dict[str, str] = {}
    if token:
        headers[header_name] = f"{auth_scheme} {token}".strip() if auth_scheme else token

    # Remote-only agent mode: any host (including localhost) is treated as an external server.
    remote = True
    start_timeout = float(timeout_cfg["start_seconds"]) if "start_seconds" in timeout_cfg else None
    submit_timeout = float(timeout_cfg["submit_seconds"]) if "submit_seconds" in timeout_cfg else None
    return ConnectionSettings(
        scheme=scheme,
        host=host,
        port=port,
        headers=headers,
        remote=remote,
        start_timeout=start_timeout,
        submit_timeout=submit_timeout,
    )


def _apply_connection_settings(args: argparse.Namespace) -> None:
    global _REQUEST_HEADERS, _HTTP_SCHEME, _WS_SCHEME, _TARGET_REMOTE
    settings = _build_connection_settings(args)
    _HTTP_SCHEME = settings.scheme
    _WS_SCHEME = "wss" if settings.scheme == "https" else "ws"
    _REQUEST_HEADERS = dict(settings.headers)
    _TARGET_REMOTE = settings.remote

    if hasattr(args, "host"):
        args.host = settings.host
    if hasattr(args, "port"):
        args.port = settings.port
    if hasattr(args, "start_timeout") and float(getattr(args, "start_timeout")) == float(DEFAULT_START_TIMEOUT):
        if settings.start_timeout is not None:
            args.start_timeout = settings.start_timeout
    if hasattr(args, "timeout") and float(getattr(args, "timeout")) == float(DEFAULT_SUBMIT_TIMEOUT):
        if settings.submit_timeout is not None:
            args.timeout = settings.submit_timeout

    # Make auth/scheme discoverable for helper modules that fetch schema/catalog directly.
    os.environ["COMFY_SCHEME"] = _HTTP_SCHEME
    if settings.headers:
        # Keep backward-compatible token env naming.
        auth_name, auth_value = next(iter(settings.headers.items()))
        os.environ["COMFY_AUTH_HEADER_NAME"] = auth_name
        if " " in auth_value:
            maybe_scheme, maybe_token = auth_value.split(" ", 1)
            os.environ["COMFY_AUTH_SCHEME"] = maybe_scheme
            os.environ["COMFY_AUTH_HEADER"] = maybe_token
        else:
            os.environ["COMFY_AUTH_HEADER"] = auth_value
        os.environ["COMFY_AUTH_HEADER_VALUE"] = auth_value
    if settings.remote:
        log(f"using remote server {_HTTP_SCHEME}://{settings.host}:{settings.port}")


def _remote_stop_guard() -> None:
    raise CliError(
        "Stop/restart are not supported in remote-only mode. "
        "Manage the server process outside comfy-agent.",
        exit_code=6,
    )


def _build_default_config_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "default_server": "localhost",
        "servers": {
            "localhost": {
                "url": "http://127.0.0.1:8188",
                "auth": {
                    "header_name": "Authorization",
                    "scheme": "Bearer",
                    "token": ""
                },
                "timeout": {
                    "start_seconds": DEFAULT_START_TIMEOUT,
                    "submit_seconds": DEFAULT_SUBMIT_TIMEOUT,
                },
            },
            "remote": {
                "url": "http://34.132.147.127:8188",
                "auth": {
                    "header_name": "Authorization",
                    "scheme": "Bearer",
                    "token": "replace-with-token"
                },
                "timeout": {
                    "start_seconds": DEFAULT_START_TIMEOUT,
                    "submit_seconds": DEFAULT_SUBMIT_TIMEOUT,
                },
            },
        },
    }


def _ui() -> TerminalUI:
    global _UI
    if _UI is None:
        _UI = TerminalUI()
    return _UI


def tail_text(path: Path, max_lines: int = 25) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    return "\n".join(lines[-max_lines:])


def _ensure_runtime_layout(data_dir: Path, comfy_dir: Path) -> None:
    # Ensure base-directory has standard Comfy folders when user relocates layout.
    for name in ("input", "output", "models", "user"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)

    custom_nodes_dir = data_dir / "custom_nodes"
    if custom_nodes_dir.exists():
        return

    source_custom_nodes = comfy_dir / "custom_nodes"
    if source_custom_nodes.exists():
        try:
            custom_nodes_dir.symlink_to(source_custom_nodes, target_is_directory=True)
            return
        except Exception:
            pass
    custom_nodes_dir.mkdir(parents=True, exist_ok=True)


def verify_runtime_dependencies() -> None:
    try:
        import sqlalchemy  # noqa: F401
    except Exception as exc:
        raise CliError(
            "Missing runtime dependency: SQLAlchemy. "
            "Install with: ./venv/bin/python -m pip install SQLAlchemy",
            exit_code=5,
        ) from exc


def _find_workspace_root() -> Path:
    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        has_flat_layout = (candidate / "comfyui-core").exists() and (candidate / "src" / "comfy_custom").exists()
        has_nested_layout = (candidate / "comfy-custom" / "comfyui-core").exists()
        has_legacy_layout = (candidate / "comfy_files").exists() and (candidate / "comfy-custom").exists()
        if has_flat_layout or has_nested_layout or has_legacy_layout:
            return candidate
    return current


def get_comfy_files_dir() -> Path:
    env_dir = os.environ.get("COMFY_FILES_DIR")
    if env_dir:
        comfy_dir = Path(env_dir).expanduser().resolve()
    else:
        workspace = _find_workspace_root()
        candidates = [
            (workspace / "comfyui-core").resolve(),
            (workspace / "comfy-custom" / "comfyui-core").resolve(),
            (workspace / "comfy_files").resolve(),
        ]
        comfy_dir = next((p for p in candidates if p.exists()), candidates[-1])

    if not comfy_dir.exists():
        raise CliError(f"Comfy core directory not found: {comfy_dir}")
    if not (comfy_dir / "main.py").exists():
        raise CliError(f"Expected Comfy main.py at: {comfy_dir / 'main.py'}")
    return comfy_dir


def _looks_like_comfy_data_dir(path: Path) -> bool:
    return (path / "input").exists() and (path / "output").exists() and (path / "models").exists()


def get_comfy_data_dir() -> Path:
    env_dir = os.environ.get("COMFY_DATA_DIR")
    if env_dir:
        data_dir = Path(env_dir).expanduser().resolve()
    else:
        workspace = _find_workspace_root()
        candidates = [
            workspace.resolve(),
            (workspace / "comfy-custom").resolve(),
            get_comfy_files_dir(),
        ]
        data_dir = next((p for p in candidates if _looks_like_comfy_data_dir(p)), get_comfy_files_dir())

    if not data_dir.exists():
        raise CliError(f"Comfy data directory not found: {data_dir}")
    if not _looks_like_comfy_data_dir(data_dir):
        raise CliError(
            f"Comfy data directory must contain input/output/models folders: {data_dir}",
            exit_code=2,
        )
    return data_dir


def get_state_dir() -> Path:
    workspace = _find_workspace_root()
    flat_state = workspace / ".state"
    nested_state = workspace / "comfy-custom" / ".state"
    state_dir = nested_state if nested_state.exists() and not flat_state.exists() else flat_state
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def state_file_path() -> Path:
    return get_state_dir() / "runtime_state.json"


def sql_workflow_file_path() -> Path:
    return get_state_dir() / "sql_last_workflow.txt"


def write_last_sql_workflow(path: Path) -> None:
    sql_workflow_file_path().write_text(str(path), encoding="utf-8")


def read_last_sql_workflow() -> Path | None:
    path = sql_workflow_file_path()
    if not path.exists():
        return None
    try:
        saved = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not saved:
        return None
    resolved = Path(saved).expanduser().resolve()
    return resolved if resolved.exists() else None


def default_sql_workflow_path() -> Path | None:
    workspace = _find_workspace_root()
    candidates = [
        workspace / "examples" / "sql_default_ui_workflow.json",
        workspace / "comfy-custom" / "examples" / "sql_default_ui_workflow.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def write_state(state: RuntimeState) -> None:
    payload = {
        "pid": state.pid,
        "host": state.host,
        "port": state.port,
        "log_path": state.log_path,
        "started_at": state.started_at,
    }
    state_file_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_state() -> RuntimeState | None:
    path = state_file_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RuntimeState(
            pid=int(data["pid"]),
            host=str(data["host"]),
            port=int(data["port"]),
            log_path=str(data["log_path"]),
            started_at=float(data["started_at"]),
        )
    except Exception:
        return None


def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_server_healthy(host: str, port: int, timeout: float = 2.0) -> bool:
    url = _http_url(host, port, "/prompt")
    req = request.Request(url, method="GET", headers=_request_headers())
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def discover_pid_by_port(port: int) -> int | None:
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{port}"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None

    if not out:
        return None
    first = out.splitlines()[0].strip()
    try:
        return int(first)
    except Exception:
        return None


def wait_for_server(
    host: str,
    port: int,
    timeout: float,
    pid: int | None = None,
    process: subprocess.Popen | None = None,
    log_path: Path | None = None,
) -> None:
    started = time.monotonic()
    last_log = 0.0
    while time.monotonic() - started < timeout:
        if is_server_healthy(host, port, timeout=1.0):
            return
        if process is not None:
            rc = process.poll()
            if rc is not None:
                details = tail_text(log_path or Path(""))
                extra = f"\nRecent server log:\n{details}" if details else ""
                raise CliError(
                    f"Comfy server process exited early with code {rc}.{extra}",
                    exit_code=3,
                )
        if pid is not None and not is_process_alive(pid):
            raise CliError(f"Comfy server process exited before becoming healthy (pid={pid}).", exit_code=3)
        elapsed = time.monotonic() - started
        if elapsed - last_log >= 2.0:
            log(f"waiting for server health at {_HTTP_SCHEME}://{host}:{port} ({int(elapsed)}s)")
            last_log = elapsed
        time.sleep(0.5)
    # Final grace check for slow startup on first run.
    if is_server_healthy(host, port, timeout=5.0):
        return
    raise CliError(f"Timed out waiting for server at {_HTTP_SCHEME}://{host}:{port}", exit_code=3)


def start_server(host: str, port: int, timeout: float = DEFAULT_START_TIMEOUT) -> RuntimeState:
    log(f"checking server on {_HTTP_SCHEME}://{host}:{port}")
    wait_for_server(host, port, timeout=timeout)
    log("server is healthy")
    return RuntimeState(pid=-1, host=host, port=port, log_path="", started_at=time.time())


def _has_synced_models(models_dir: Path) -> bool:
    if not models_dir.exists():
        return False
    for path in models_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.startswith("put_") or name in {".ds_store", ".gitkeep", "readme.md"}:
            continue
        return True
    return False


def ensure_server_running(host: str, port: int, timeout: float = DEFAULT_START_TIMEOUT) -> RuntimeState:
    if is_server_healthy(host, port):
        return RuntimeState(pid=-1, host=host, port=port, log_path="", started_at=time.time())
    return start_server(host=host, port=port, timeout=timeout)


def validate_api_prompt(workflow_data: Any) -> dict[str, Any]:
    if not isinstance(workflow_data, dict) or not workflow_data:
        raise CliError("Workflow JSON must be a non-empty object in Comfy API prompt format.", exit_code=2)

    for node_id, node_data in workflow_data.items():
        if not isinstance(node_id, str):
            raise CliError("Workflow node ids must be strings in API prompt JSON.", exit_code=2)
        if not isinstance(node_data, dict):
            raise CliError(f"Workflow node '{node_id}' must be a JSON object.", exit_code=2)
        if "class_type" not in node_data or "inputs" not in node_data:
            raise CliError(
                f"Workflow node '{node_id}' must contain 'class_type' and 'inputs'.",
                exit_code=2,
            )
    return workflow_data


def load_workflow(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise CliError(f"Workflow file not found: {path}", exit_code=2)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid workflow JSON: {exc}", exit_code=2) from exc
    return validate_api_prompt(data)


def apply_no_cache_mutation(workflow: dict[str, Any]) -> int:
    """
    Force re-execution by randomizing seed-like inputs.
    Returns number of nodes mutated.
    """
    mutated = 0
    for _node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        inputs = node_data.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if "seed" in inputs:
            try:
                # Keep within positive signed 32-bit range for broad node compatibility.
                inputs["seed"] = random.randint(1, 2_147_483_647)
                mutated += 1
            except Exception:
                continue
    return mutated


def _looks_like_link(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    src, out = value
    if not isinstance(src, (str, int)):
        return False
    return isinstance(out, int)


def _graph_from_api_prompt(workflow: dict[str, Any], catalog):
    from comfy_custom.validate.runtime import build_graph_from_api_prompt

    try:
        return build_graph_from_api_prompt(workflow, catalog)
    except ValueError as exc:
        raise CliError(str(exc), exit_code=2) from exc


def _is_ui_workflow_json(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("nodes"), list)
        and isinstance(data.get("links"), list)
    )


def validate_workflow(workflow_path: Path, host: str, port: int) -> int:
    log(f"loading workflow for validation: {workflow_path}")
    if not workflow_path.exists():
        raise CliError(f"Workflow file not found: {workflow_path}", exit_code=2)
    try:
        raw_data = json.loads(workflow_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid workflow JSON: {exc}", exit_code=2) from exc

    log("syncing nodes and models before validation")
    _sync_schema_and_models(
        host=host,
        port=port,
        timeout=DEFAULT_SUBMIT_TIMEOUT,
        start_timeout=DEFAULT_START_TIMEOUT,
        write_report=True,
    )

    from comfy_custom.validate.runtime import (
        GraphValidationError,
        build_catalog,
        validate_asset_references,
        validate_graph,
        validate_model_references,
    )

    log("fetching node catalog from server")
    try:
        catalog = build_catalog(host, port)
    except Exception as exc:
        raise CliError(f"Validation failed fetching node catalog: {exc}", exit_code=3) from exc

    if not catalog.node_types:
        raise CliError("Validation failed: node catalog is empty.", exit_code=3)

    mapping_warnings: list[str] = []
    if _is_ui_workflow_json(raw_data):
        raise CliError(
            "UI workflow JSON validation is not supported in local validate mode. "
            "Export API prompt JSON from ComfyUI and retry.",
            exit_code=2,
        )
    workflow = validate_api_prompt(raw_data)
    graph = _graph_from_api_prompt(workflow, catalog)

    try:
        validate_graph(graph, catalog, verbose_errors=False)
    except GraphValidationError as exc:
        print("validation_failed", flush=True)
        for err in exc.errors:
            print(f"- {err}", flush=True)
        return 2

    try:
        checked_models, missing_models = validate_model_references(host, port, graph)
        checked_assets, missing_assets = validate_asset_references(host, port, graph)
    except Exception as exc:
        raise CliError(f"Validation reference checks failed: {exc}", exit_code=3) from exc

    if mapping_warnings:
        print("validation_warnings", flush=True)
        for warning in mapping_warnings:
            print(f"- {warning}", flush=True)

    if missing_models or missing_assets:
        print("validation_failed", flush=True)
        if missing_models:
            print("missing_models", flush=True)
            for item in missing_models:
                model_name = item.get("model")
                category = item.get("category")
                node_id = item.get("node_id")
                print(f"- node={node_id} category={category} model={model_name}", flush=True)
        if missing_assets:
            print("missing_assets", flush=True)
            for item in missing_assets:
                asset = item.get("asset")
                folder_type = item.get("folder_type")
                node_id = item.get("node_id")
                print(f"- node={node_id} folder={folder_type} asset={asset}", flush=True)
        return 2

    print(
        f"validation_ok nodes={len(graph.nodes)} edges={len(graph.edges)} "
        f"checked_models={len(checked_models)} checked_assets={len(checked_assets)}",
        flush=True,
    )
    return 0


def post_prompt(host: str, port: int, payload: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    url = _http_url(host, port, "/prompt")
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers=_request_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_data = response.read().decode("utf-8")
            return json.loads(response_data) if response_data else {}
    except error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        if "prompt_no_outputs" in err_body:
            err_body = (
                f"{err_body}\nHint: workflow must include at least one output node "
                "(for example SaveImage). Export from Comfy UI using File -> Export (API)."
            )
        raise CliError(f"Prompt submission failed ({exc.code}): {err_body}", exit_code=4) from exc
    except Exception as exc:
        raise CliError(f"Prompt submission failed: {exc}", exit_code=4) from exc


def progress_line(value: int, total: int, width: int = 30) -> str:
    pct = 0 if total <= 0 else int((value / total) * 100)
    pct = max(0, min(100, pct))
    filled = int(width * pct / 100)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {pct}%"


def _parse_ws_event_with_pct(raw_message: str, prompt_id: str) -> tuple[str, str | None, int | None]:
    try:
        payload = json.loads(raw_message)
    except json.JSONDecodeError:
        return ("ignore", None, None)

    event_type = payload.get("type")
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return ("ignore", None, None)

    if event_type == "progress" and data.get("prompt_id") == prompt_id:
        value = int(data.get("value", 0) or 0)
        total = int(data.get("max", 0) or 0)
        pct = 0 if total <= 0 else int((value / total) * 100)
        pct = max(0, min(100, pct))
        return ("progress", progress_line(value, total), pct)

    if event_type == "executing" and data.get("prompt_id") == prompt_id and data.get("node") is None:
        return ("executed", "executed", 100)

    if event_type in {"execution_error", "error"} and (data.get("prompt_id") in {None, prompt_id}):
        return ("failed", f"failed: {json.dumps(data, ensure_ascii=True)}", None)

    return ("ignore", None, None)


def parse_ws_event(raw_message: str, prompt_id: str) -> tuple[str, str | None]:
    event, text, _pct = _parse_ws_event_with_pct(raw_message=raw_message, prompt_id=prompt_id)
    return (event, text)


def submit_api_prompt(
    workflow: dict[str, Any],
    host: str,
    port: int,
    timeout: float,
    no_cache: bool = False,
) -> dict[str, Any]:
    workflow = validate_api_prompt(workflow)
    if no_cache:
        mutated = apply_no_cache_mutation(workflow)
        if mutated > 0:
            log(f"--no-cache enabled: randomized seed on {mutated} node(s)")
        else:
            log("--no-cache enabled, but no 'seed' inputs were found to mutate")
    log("ensuring server is running")
    ensure_server_running(host=host, port=port, timeout=DEFAULT_START_TIMEOUT)

    client_id = str(uuid.uuid4())
    prompt_id = str(uuid.uuid4())

    ws_url = _ws_url(host, port, f"/ws?{parse.urlencode({'clientId': client_id})}")
    ws = websocket.WebSocket()
    try:
        log(f"connecting websocket: {ws_url}")
        ws_headers = [f"{k}: {v}" for k, v in _request_headers().items()]
        ws.connect(ws_url, timeout=10, header=ws_headers or None)
    except Exception as exc:
        raise CliError(f"WebSocket connection failed: {exc}", exit_code=4) from exc

    progress_state = None
    try:
        submit_response = post_prompt(
            host=host,
            port=port,
            payload={"prompt": workflow, "client_id": client_id, "prompt_id": prompt_id},
        )
        log("prompt submitted to /prompt")
        server_prompt_id = str(submit_response.get("prompt_id", ""))
        if server_prompt_id and server_prompt_id != prompt_id:
            prompt_id = server_prompt_id
        progress_state = _ui().submit_begin()

        ws.settimeout(1.0)
        started = time.monotonic()

        while time.monotonic() - started < timeout:
            try:
                message = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:
                raise CliError(f"WebSocket disconnected: {exc}", exit_code=4) from exc

            if not isinstance(message, str):
                continue

            event, text, pct = _parse_ws_event_with_pct(message, prompt_id=prompt_id)
            if event == "progress" and text is not None and pct is not None:
                _ui().submit_update(progress_state, text, pct)
            elif event == "executed":
                _ui().submit_done(progress_state)
                return {"prompt_id": prompt_id}
            elif event == "failed" and text is not None:
                _ui().submit_fail(progress_state, text)
                raise CliError(text, exit_code=4)

        raise CliError(f"Timed out waiting for workflow execution after {timeout:.1f}s", exit_code=4)
    finally:
        if progress_state is not None and progress_state.progress is not None:
            try:
                progress_state.progress.stop()
            except Exception:
                pass
        try:
            ws.close()
        except Exception:
            pass


def submit_workflow(workflow_path: Path, host: str, port: int, timeout: float, no_cache: bool = False) -> None:
    log(f"loading workflow: {workflow_path}")
    workflow = load_workflow(workflow_path)
    submit_api_prompt(workflow=workflow, host=host, port=port, timeout=timeout, no_cache=no_cache)


def _split_sql_statements(text: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    quote: str | None = None

    for ch in text:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement + ";")
            buf = []
            continue
        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _build_sql_engine(args: argparse.Namespace) -> LocalComfySQLEngine:
    return LocalComfySQLEngine(
        comfy_dir=_find_workspace_root(),
        state_dir=get_state_dir(),
        host=args.host,
        port=args.port,
        scheme=_HTTP_SCHEME,
        ensure_server_running=lambda host, port: ensure_server_running(host=host, port=port, timeout=DEFAULT_START_TIMEOUT),
        validate_api_prompt=validate_api_prompt,
        submit_api_prompt=submit_api_prompt,
    )


def _render_sql_result(result: dict[str, Any], table_filter: str = "all") -> None:
    ui = _ui()
    if ui.styled:
        _render_sql_result_styled(result=result, table_filter=table_filter, ui=ui)
        return

    def _as_count(value: Any) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, int):
            return value
        return 0

    action = result.get("action")
    if action == "create_table":
        print(f"table_created name={result.get('table')} workflow={result.get('workflow_path')}", flush=True)
        validation = result.get("validation")
        if isinstance(validation, dict):
            print(
                "validated "
                f"nodes={validation.get('nodes')} "
                f"edges={validation.get('edges')} "
                f"checked_models={_as_count(validation.get('checked_models'))} "
                f"checked_assets={_as_count(validation.get('checked_assets'))}",
                flush=True,
            )
        return
    if action == "create_template":
        print(f"template_created name={result.get('table')} workflow={result.get('workflow_path')}", flush=True)
        validation = result.get("validation")
        if isinstance(validation, dict):
            print(
                "validated "
                f"nodes={validation.get('nodes')} "
                f"edges={validation.get('edges')} "
                f"checked_models={_as_count(validation.get('checked_models'))} "
                f"checked_assets={_as_count(validation.get('checked_assets'))}",
                flush=True,
            )
        return
    if action == "create_preset":
        print(
            f"preset_created template={result.get('template_name')} name={result.get('preset_name')}",
            flush=True,
        )
        return
    if action == "create_profile":
        print(f"profile_created name={result.get('profile_name')}", flush=True)
        return
    if action == "set_meta":
        print(f"meta_set table={result.get('table')}", flush=True)
        return
    if action == "unset_meta":
        print(f"meta_unset table={result.get('table')}", flush=True)
        return
    if action == "drop_preset":
        print(
            f"preset_dropped template={result.get('template_name')} name={result.get('preset_name')}",
            flush=True,
        )
        return
    if action == "drop_profile":
        print(f"profile_dropped name={result.get('profile_name')}", flush=True)
        return
    if action == "describe_preset":
        print(json.dumps(result, indent=2, ensure_ascii=True), flush=True)
        return
    if action == "describe_profile":
        print(json.dumps(result, indent=2, ensure_ascii=True), flush=True)
        return
    if action == "drop_table":
        print(f"table_dropped name={result.get('table')}", flush=True)
        return
    if action == "refresh_schema":
        print(f"schema_refreshed tables={result.get('tables')}", flush=True)
        return
    if action == "describe_tables":
        table_filter = str(result.get("table_filter", table_filter) or "all")
        rows = result.get("rows", [])
        workflows = [r for r in rows if isinstance(r, dict) and r.get("kind") == "workflow"]
        templates = [r for r in rows if isinstance(r, dict) and r.get("kind") == "template"]
        nodes = [r for r in rows if isinstance(r, dict) and r.get("kind") == "node"]
        presets = [r for r in rows if isinstance(r, dict) and r.get("kind") == "preset"]
        profiles = [r for r in rows if isinstance(r, dict) and r.get("kind") == "profile"]
        models_tables = [r for r in rows if isinstance(r, dict) and r.get("kind") == "models_table"]

        print(f"tables_total={len(rows)}", flush=True)
        print(
            " ".join(
                [
                    f"workflows={len(workflows)}",
                    f"templates={len(templates)}",
                    f"nodes={len(nodes)}",
                    f"presets={len(presets)}",
                    f"profiles={len(profiles)}",
                    f"models={len(models_tables)}",
                ]
            ),
            flush=True,
        )

        if table_filter in {"all", "workflows"}:
            print("WORKFLOWS", flush=True)
            if workflows:
                for row in workflows:
                    print(
                        f"- {row.get('table')} (workflow_path={row.get('workflow_path')}, has_meta={bool(row.get('has_meta'))})",
                        flush=True,
                    )
            else:
                print("- (none)", flush=True)

        if table_filter in {"all", "templates"}:
            print("TEMPLATES", flush=True)
            if templates:
                for row in templates:
                    has_meta = row.get("has_meta")
                    if has_meta is None:
                        print(f"- {row.get('table')}", flush=True)
                    else:
                        print(f"- {row.get('table')} (has_meta={bool(has_meta)})", flush=True)
            else:
                print("- (none)", flush=True)

        if table_filter in {"all", "nodes"}:
            print("NODES", flush=True)
            for row in nodes:
                table = row.get("table")
                category = row.get("category", "")
                print(f"- {table} (category={category})", flush=True)
        if table_filter in {"all", "presets"}:
            print("PRESETS", flush=True)
            if presets:
                for row in presets:
                    print(
                        f"- {row.get('template_name')}.{row.get('preset_name')}",
                        flush=True,
                    )
            else:
                print("- (none)", flush=True)
        if table_filter in {"all", "profiles"}:
            print("PROFILES", flush=True)
            if profiles:
                for row in profiles:
                    print(f"- {row.get('profile_name')}", flush=True)
            else:
                print("- (none)", flush=True)
        if table_filter in {"all", "models"}:
            print("MODELS", flush=True)
            if models_tables:
                for row in models_tables:
                    print(f"- {row.get('table')} ({row.get('description', '')})", flush=True)
            else:
                print("- (none)", flush=True)
        return
    if action == "models_select":
        rows = result.get("rows", [])
        print(f"models_count={len(rows)}", flush=True)
        for row in rows:
            print(
                f"- category={row.get('category')} name={row.get('name')} "
                f"path={row.get('path')} folder={row.get('folder', '')}",
                flush=True,
            )
        return
    if action == "describe":
        print(json.dumps(result, indent=2, ensure_ascii=True), flush=True)
        return
    if action in {"explain", "compiled"}:
        print(action, flush=True)
        validation = result.get("validation")
        if isinstance(validation, dict) and validation.get("status") == "ok":
            print(
                "validated "
                f"nodes={validation.get('nodes')} "
                f"edges={validation.get('edges')} "
                f"checked_models={_as_count(validation.get('checked_models'))} "
                f"checked_assets={_as_count(validation.get('checked_assets'))}",
                flush=True,
            )
        path = result.get("api_prompt_path")
        if path:
            print(f"api_prompt: {path}", flush=True)
        return
    if action == "select":
        upload_preflight = result.get("upload_preflight")
        if isinstance(upload_preflight, dict):
            print(
                f"upload_preflight uploaded={upload_preflight.get('uploaded_count', 0)} "
                f"skipped_existing={upload_preflight.get('skipped_existing_count', 0)} "
                f"failed={upload_preflight.get('failed_count', 0)}",
                flush=True,
            )
            for item in upload_preflight.get("failed", []) or []:
                print(
                    f"- upload_failed local={item.get('local_path')} remote={item.get('remote_path')} "
                    f"error={item.get('error')}",
                    flush=True,
                )
        path = result.get("api_prompt_path")
        if path:
            print(f"api_prompt: {path}", flush=True)
        downloaded = result.get("downloaded_outputs")
        if isinstance(downloaded, list):
            print(f"downloaded_outputs count={len(downloaded)}", flush=True)
            for item in downloaded:
                print(f"- {item}", flush=True)
        download_failures = result.get("download_failures")
        if isinstance(download_failures, list) and download_failures:
            print(f"download_failures count={len(download_failures)}", flush=True)
            for item in download_failures:
                print(
                    "- download_failed "
                    f"file={item.get('filename')} "
                    f"category={item.get('failure_category')} "
                    f"next={item.get('next_action')} "
                    f"error={item.get('error')}",
                    flush=True,
                )
        return
    print(json.dumps(result, indent=2, ensure_ascii=True), flush=True)


def _render_sql_result_styled(result: dict[str, Any], table_filter: str, ui: TerminalUI) -> None:
    def _as_count(value: Any) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, int):
            return value
        return 0

    action = result.get("action")
    if action in {"create_table", "create_template"}:
        ui.line(
            "[green]" + ("template_created" if action == "create_template" else "table_created") + "[/] "
            f"name={result.get('table')} "
            f"workflow={result.get('workflow_path')}"
        )
        validation = result.get("validation")
        if isinstance(validation, dict):
            ui.line(
                "[green]validated[/] "
                f"nodes={validation.get('nodes')} "
                f"edges={validation.get('edges')} "
                f"checked_models={_as_count(validation.get('checked_models'))} "
                f"checked_assets={_as_count(validation.get('checked_assets'))}"
            )
        return
    if action in {"describe_preset", "describe_profile", "describe"}:
        ui.print_json(result)
        return

    if action == "describe_tables":
        table_filter = str(result.get("table_filter", table_filter) or "all")
        rows = result.get("rows", [])
        workflows = [r for r in rows if isinstance(r, dict) and r.get("kind") == "workflow"]
        templates = [r for r in rows if isinstance(r, dict) and r.get("kind") == "template"]
        nodes = [r for r in rows if isinstance(r, dict) and r.get("kind") == "node"]
        presets = [r for r in rows if isinstance(r, dict) and r.get("kind") == "preset"]
        profiles = [r for r in rows if isinstance(r, dict) and r.get("kind") == "profile"]
        models_tables = [r for r in rows if isinstance(r, dict) and r.get("kind") == "models_table"]
        ui.line(
            "[bold cyan]tables[/] "
            f"total={len(rows)} workflows={len(workflows)} templates={len(templates)} "
            f"nodes={len(nodes)} presets={len(presets)} profiles={len(profiles)} models={len(models_tables)}"
        )
        if table_filter in {"all", "workflows"}:
            ui.print_table(
                "WORKFLOWS",
                ["name", "workflow_path", "has_meta"],
                [
                    [
                        str(r.get("table", "")),
                        str(r.get("workflow_path", "")),
                        str(bool(r.get("has_meta"))).lower(),
                    ]
                    for r in workflows
                ],
            )
        if table_filter in {"all", "templates"}:
            ui.print_table(
                "TEMPLATES",
                ["name", "has_meta"],
                [
                    [
                        str(r.get("table", "")),
                        str(bool(r.get("has_meta"))).lower() if "has_meta" in r else "",
                    ]
                    for r in templates
                ],
            )
        if table_filter in {"all", "nodes"}:
            ui.print_table(
                "NODES",
                ["class_type", "category"],
                [[str(r.get("table", "")), str(r.get("category", ""))] for r in nodes],
            )
        if table_filter in {"all", "presets"}:
            ui.print_table(
                "PRESETS",
                ["template", "preset"],
                [[str(r.get("template_name", "")), str(r.get("preset_name", ""))] for r in presets],
            )
        if table_filter in {"all", "profiles"}:
            ui.print_table(
                "PROFILES",
                ["profile"],
                [[str(r.get("profile_name", ""))] for r in profiles],
            )
        if table_filter in {"all", "models"}:
            ui.print_table(
                "MODELS",
                ["table", "description"],
                [[str(r.get("table", "")), str(r.get("description", ""))] for r in models_tables],
            )
        return
    if action == "models_select":
        rows = result.get("rows", [])
        ui.line(f"[bold blue]models[/] count={len(rows)}")
        ui.print_table(
            "MODEL INVENTORY",
            ["category", "name", "path", "folder"],
            [
                [
                    str(r.get("category", "")),
                    str(r.get("name", "")),
                    str(r.get("path", "")),
                    str(r.get("folder", "")),
                ]
                for r in rows
            ],
        )
        return

    if action in {
        "create_table",
        "create_template",
        "drop_table",
        "create_preset",
        "drop_preset",
        "create_profile",
        "drop_profile",
        "set_meta",
        "unset_meta",
        "refresh_schema",
    }:
        ui.line("[green]" + json.dumps(result, ensure_ascii=True) + "[/]")
        return

    if action in {"explain", "compiled"}:
        ui.line(f"[bold blue]{action}[/]")
        validation = result.get("validation")
        if isinstance(validation, dict) and validation.get("status") == "ok":
            ui.line(
                "[green]validated[/] "
                f"nodes={validation.get('nodes')} "
                f"edges={validation.get('edges')} "
                f"checked_models={_as_count(validation.get('checked_models'))} "
                f"checked_assets={_as_count(validation.get('checked_assets'))}"
            )
        path = result.get("api_prompt_path")
        if path:
            ui.line(f"[bold]api_prompt:[/] {path}")
        return

    if action == "select":
        upload_preflight = result.get("upload_preflight")
        if isinstance(upload_preflight, dict):
            ui.line(
                "[bold yellow]upload_preflight[/] "
                f"uploaded={upload_preflight.get('uploaded_count', 0)} "
                f"skipped_existing={upload_preflight.get('skipped_existing_count', 0)} "
                f"failed={upload_preflight.get('failed_count', 0)}"
            )
            for item in upload_preflight.get("failed", []) or []:
                ui.line(
                    f"- [red]upload_failed[/] local={item.get('local_path')} "
                    f"remote={item.get('remote_path')} error={item.get('error')}"
                )
        path = result.get("api_prompt_path")
        if path:
            ui.line(f"[bold]api_prompt:[/] {path}")
        downloaded = result.get("downloaded_outputs")
        if isinstance(downloaded, list):
            ui.line(f"[bold blue]downloaded_outputs[/] count={len(downloaded)}")
            for item in downloaded:
                ui.line(f"- {item}")
        download_failures = result.get("download_failures")
        if isinstance(download_failures, list) and download_failures:
            ui.line(f"[bold red]download_failures[/] count={len(download_failures)}")
            for item in download_failures:
                ui.line(
                    f"- file={item.get('filename')} "
                    f"category={item.get('failure_category')} "
                    f"next={item.get('next_action')} "
                    f"error={item.get('error')}"
                )
        return

    ui.print_json(result if isinstance(result, dict) else {"result": result})


def _is_destructive_sql(sql_text: str) -> bool:
    text = sql_text.strip().rstrip(";").strip()
    upper = text.upper()
    if upper.startswith(("DROP ", "DELETE ", "TRUNCATE ", "ALTER ")):
        return True
    if upper.startswith("CREATE PRESET ") or upper.startswith("CREATE PROFILE "):
        return True
    return False


def _confirm_sql_if_needed(sql_text: str, yes: bool) -> None:
    if yes or not _is_destructive_sql(sql_text):
        return
    answer = input("This statement can change state. Continue? [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        raise CliError("Cancelled by user.", exit_code=130)


def _execute_sql_statement(engine: LocalComfySQLEngine, sql_text: str, args: argparse.Namespace, statement_index: int) -> None:
    _confirm_sql_if_needed(sql_text=sql_text, yes=bool(getattr(args, "yes", False)))
    try:
        result = engine.execute_sql(
            sql=sql_text,
            compile_only=args.compile_only,
            no_cache=args.no_cache,
            timeout=args.timeout,
            statement_index=statement_index,
            download_output=bool(getattr(args, "download_output", False)),
            download_dir=getattr(args, "download_dir", None),
            upload_mode=str(getattr(args, "upload_mode", "strict")),
        )
    except SQLEngineError as exc:
        raise CliError(str(exc), exit_code=exc.exit_code) from exc
    _render_sql_result(result, table_filter=getattr(args, "show_tables", "all") or "all")


def _run_sql_terminal(args: argparse.Namespace, engine: LocalComfySQLEngine) -> int:
    _setup_sql_readline_history()
    print("ComfySQL terminal. End each statement with ';'. Type '.exit' or '.quit' to leave.", flush=True)
    buf: list[str] = []
    statement_index = 1

    while True:
        prompt = "comfysql> " if not buf else "... "
        try:
            line = input(prompt)
        except EOFError:
            print("", flush=True)
            return 0
        except KeyboardInterrupt:
            print("", flush=True)
            return 130

        stripped = line.strip()
        if not buf and stripped in {".exit", ".quit"}:
            return 0
        if not buf and stripped in {"clear", "clear;", ".clear"}:
            # Terminal convenience command: clear screen without SQL parsing.
            print("\033[2J\033[H", end="", flush=True)
            continue
        if not stripped and not buf:
            continue

        buf.append(line)
        chunk = "\n".join(buf)
        statements = _split_sql_statements(chunk)
        if not statements:
            continue

        for statement in statements[:-1]:
            try:
                _execute_sql_statement(
                    engine=engine,
                    sql_text=statement,
                    args=args,
                    statement_index=statement_index,
                )
            except CliError as exc:
                print(str(exc), flush=True)
            statement_index += 1

        last = statements[-1]
        if last.strip().endswith(";"):
            try:
                _execute_sql_statement(
                    engine=engine,
                    sql_text=last,
                    args=args,
                    statement_index=statement_index,
                )
            except CliError as exc:
                print(str(exc), flush=True)
            statement_index += 1
            buf = []
        else:
            buf = [last]


SQL_TERMINAL_HINTS = [
    "SELECT",
    "EXPLAIN",
    "DESCRIBE",
    "SHOW TABLES",
    "CREATE TABLE",
    "DROP TABLE",
    "CREATE PRESET",
    "DROP PRESET",
    "DESCRIBE PRESET",
    "CREATE PROFILE",
    "DROP PROFILE",
    "DESCRIBE PROFILE",
    "REFRESH SCHEMA",
    ".exit",
    ".quit",
    ".clear",
    "clear",
]


def _complete_path_token(token: str) -> list[str]:
    quote = ""
    raw = token
    if token.startswith(("'", '"')):
        quote = token[0]
        raw = token[1:]

    if raw.startswith("~"):
        expanded = os.path.expanduser(raw)
    else:
        expanded = raw

    path = Path(expanded)
    if raw.endswith("/"):
        base_dir = path
        prefix = ""
    else:
        base_dir = path.parent if str(path.parent) else Path(".")
        prefix = path.name

    try:
        entries = sorted(base_dir.iterdir(), key=lambda p: p.name.lower())
    except Exception:
        return []

    suggestions: list[str] = []
    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        full = base_dir / entry.name
        rendered = str(full)
        if entry.is_dir():
            rendered += "/"
        if quote:
            rendered = quote + rendered
        suggestions.append(rendered)
    return suggestions


def _sql_completer(text: str, state: int) -> str | None:
    if state == 0:
        if "/" in text or text.startswith(("~", ".", "'", '"')):
            matches = _complete_path_token(text)
        else:
            upper = text.upper()
            matches = [hint for hint in SQL_TERMINAL_HINTS if hint.startswith(upper if upper else "")]
        _sql_completer._matches = matches  # type: ignore[attr-defined]
    matches = getattr(_sql_completer, "_matches", [])
    if state < len(matches):
        return matches[state]
    return None


def _setup_sql_readline_history() -> None:
    try:
        import readline  # type: ignore
    except Exception:
        return

    history_path = get_state_dir() / "comfysql_history.txt"
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        readline.read_history_file(str(history_path))
    except FileNotFoundError:
        pass
    except Exception:
        return

    # Keep a bounded persistent history so arrow-up works across sessions.
    try:
        readline.set_history_length(1000)
    except Exception:
        pass

    try:
        readline.set_completer_delims(" \t\n;=(),")
    except Exception:
        pass
    try:
        readline.set_completer(_sql_completer)
    except Exception:
        pass
    # GNU readline and macOS libedit compatibility.
    for bind in ("tab: complete", "bind ^I rl_complete"):
        try:
            readline.parse_and_bind(bind)
        except Exception:
            continue

    def _save_history() -> None:
        try:
            readline.write_history_file(str(history_path))
        except Exception:
            return

    atexit.register(_save_history)


def cmd_start(args: argparse.Namespace) -> int:
    state = start_server(host=args.host, port=args.port, timeout=args.start_timeout)
    print(
        f"server_started pid={state.pid} host={state.host} port={state.port} log={state.log_path}",
        flush=True,
    )
    if not _REQUEST_HEADERS:
        log("no auth header configured (ok if server is public)")
    models_dir = get_comfy_data_dir() / "models"
    if not _has_synced_models(models_dir):
        log(
            "no synced models found under models/. "
            "Run `comfy-agent pull --yes` to sync defaults, or use your own model files."
        )
    print(f"server_healthy host={args.host} port={args.port}")
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    workflow_path = Path(args.workflow).expanduser().resolve()
    if not args.skip_validate:
        log("running preflight validation before submit")
        validation_code = validate_workflow(
            workflow_path=workflow_path,
            host=args.host,
            port=args.port,
        )
        if validation_code != 0:
            return validation_code

    submit_workflow(
        workflow_path=workflow_path,
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        no_cache=args.no_cache,
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    return validate_workflow(
        workflow_path=Path(args.workflow).expanduser().resolve(),
        host=args.host,
        port=args.port,
    )


def cmd_sql(args: argparse.Namespace) -> int:
    engine = _build_sql_engine(args)
    if bool(getattr(args, "dry_run", False)):
        args.compile_only = True
    output_mode = str(getattr(args, "output_mode", "") or "").strip().lower()
    if output_mode:
        args.download_output = output_mode == "download"
    if getattr(args, "show_tables", None):
        if args.show_tables == "all":
            args.sql = "SHOW TABLES;"
        else:
            args.sql = f"SHOW TABLES {args.show_tables};"

    sql_raw = args.sql
    if sql_raw and args.sql_file:
        raise CliError("Use either --sql or --sql-file, not both.", exit_code=2)

    if args.sql_file:
        sql_path = Path(args.sql_file).expanduser().resolve()
        if not sql_path.exists():
            raise CliError(f"SQL file not found: {sql_path}", exit_code=2)
        sql_raw = sql_path.read_text(encoding="utf-8")

    if sql_raw is None:
        return _run_sql_terminal(args=args, engine=engine)

    statements = _split_sql_statements(sql_raw)
    if not statements:
        raise CliError("No SQL statements found.", exit_code=2)

    for index, statement in enumerate(statements, start=1):
        _execute_sql_statement(
            engine=engine,
            sql_text=statement,
            args=args,
            statement_index=index,
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    healthy = is_server_healthy(args.host, args.port, timeout=1.5)
    if healthy:
        print(f"status=running_remote host={args.host} port={args.port}")
    else:
        print(f"status=stopped_remote host={args.host} port={args.port}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []
    base = f"{_HTTP_SCHEME}://{args.host}:{args.port}"
    timeout = float(getattr(args, "timeout", 5.0) or 5.0)

    healthy = is_server_healthy(args.host, args.port, timeout=timeout)
    checks.append(("health", healthy, f"url={base}"))

    try:
        req = request.Request(
            _http_url(args.host, args.port, "/object_info"),
            headers=_request_headers({}),
            method="GET",
        )
        with request.urlopen(req, timeout=timeout) as resp:
            _ = json.loads(resp.read().decode("utf-8"))
        checks.append(("object_info", True, "ok"))
    except Exception as exc:
        checks.append(("object_info", False, str(exc)))

    try:
        req = request.Request(
            _http_url(args.host, args.port, "/models"),
            headers=_request_headers({}),
            method="GET",
        )
        with request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        checks.append(("models", isinstance(payload, list), f"type={type(payload).__name__}"))
    except Exception as exc:
        checks.append(("models", False, str(exc)))

    ws_client_id = str(uuid.uuid4())
    ws_url = _ws_url(args.host, args.port, f"/ws?clientId={ws_client_id}")
    try:
        conn = websocket.create_connection(
            ws_url,
            timeout=timeout,
            header=[f"{k}: {v}" for k, v in _REQUEST_HEADERS.items()],
        )
        conn.close()
        checks.append(("websocket", True, "ok"))
    except Exception as exc:
        checks.append(("websocket", False, str(exc)))

    auth_ok = bool(_REQUEST_HEADERS)
    checks.append(("auth_header", auth_ok, "configured" if auth_ok else "not_configured"))

    failed = 0
    for name, ok, detail in checks:
        status = "ok" if ok else "fail"
        print(f"doctor {name}={status} detail={detail}", flush=True)
        if not ok:
            failed += 1

    if failed:
        print(f"doctor_summary status=fail failed_checks={failed}", flush=True)
        return 3
    print("doctor_summary status=ok failed_checks=0", flush=True)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    state = read_state()
    if state is None and not is_server_healthy(args.host, args.port, timeout=1.5):
        print(f"server_not_running host={args.host} port={args.port}", flush=True)
        return 0
    _remote_stop_guard()
    return 6


def cmd_restart(args: argparse.Namespace) -> int:
    _remote_stop_guard()
    return 6


def cmd_pull(args: argparse.Namespace) -> int:
    config_path = Path(getattr(args, "config", None) or (_find_workspace_root() / "hf_pull_config.json")).expanduser().resolve()
    try:
        models_base = get_comfy_data_dir()
    except CliError:
        models_base = get_comfy_files_dir()
    try:
        from comfy_custom.hf_pull import PullError, ensure_default_hf_pull_config

        ensure_default_hf_pull_config(config_path)
        report = execute_pull(
            config_path=config_path,
            models_dir=models_base / "models",
            state_dir=get_state_dir(),
            yes=bool(getattr(args, "yes", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            log_fn=log,
        )
    except PullError as exc:
        raise CliError(str(exc), exit_code=exc.exit_code) from exc

    print(
        "pull_done "
        f"copied={report.copied} skipped_exists={report.skipped_exists} failed={report.failed} "
        f"bytes_copied={report.bytes_copied} dry_run={'true' if report.dry_run else 'false'}",
        flush=True,
    )
    return 4 if report.failed else 0


def execute_pull(**kwargs):
    from comfy_custom.hf_pull import execute_pull_hf

    return execute_pull_hf(**kwargs)


def _default_assets_dir() -> Path:
    return (_find_workspace_root() / "input" / "assets").resolve()


def _collect_asset_files(*, source: str | None, all_assets: bool) -> list[Path]:
    if all_assets:
        assets_dir = _default_assets_dir()
        if not assets_dir.exists() or not assets_dir.is_dir():
            raise CliError(f"Assets folder not found: {assets_dir}", exit_code=2)
        files = sorted([p for p in assets_dir.rglob("*") if p.is_file()])
        if not files:
            raise CliError(f"No files found under assets folder: {assets_dir}", exit_code=2)
        return files

    if not source:
        raise CliError("Provide a source file/folder or use --all.", exit_code=2)

    src = Path(source).expanduser()
    if not src.is_absolute():
        src = (Path.cwd() / src).resolve()
    else:
        src = src.resolve()
    if not src.exists():
        raise CliError(f"Source path not found: {src}", exit_code=2)
    if src.is_file():
        return [src]
    if src.is_dir():
        files = sorted([p for p in src.rglob("*") if p.is_file()])
        if not files:
            raise CliError(f"No files found in source folder: {src}", exit_code=2)
        return files
    raise CliError(f"Unsupported source path: {src}", exit_code=2)


def cmd_copy_assets(args: argparse.Namespace) -> int:
    files = _collect_asset_files(source=getattr(args, "source", None), all_assets=bool(getattr(args, "all", False)))
    log(
        f"copy_assets host={args.host}:{args.port} files={len(files)} "
        f"dry_run={'true' if args.dry_run else 'false'} mode=http_upload"
    )

    if args.dry_run:
        print(f"copy_assets_plan files={len(files)} mode=http_upload", flush=True)
        for f in files:
            print(f"- {f}", flush=True)
        return 0

    engine = _build_sql_engine(args)
    prompt: dict[str, Any] = {}
    for idx, file_path in enumerate(files, start=1):
        prompt[str(idx)] = {
            "class_type": "LoadImage",
            "inputs": {"image": str(file_path)},
        }

    try:
        _patched, report = engine._auto_upload_local_assets(prompt, timeout=float(getattr(args, "timeout", DEFAULT_SUBMIT_TIMEOUT)))
    except SQLEngineError as exc:
        raise CliError(str(exc), exit_code=exc.exit_code) from exc

    uploaded = int(report.get("uploaded_count", 0))
    skipped = int(report.get("skipped_existing_count", 0))
    failed = int(report.get("failed_count", 0))
    print(f"copy_assets_done uploaded={uploaded} skipped_existing={skipped} failed={failed}", flush=True)
    for item in report.get("failed", []) or []:
        print(
            f"- copy_failed local={item.get('local_path')} remote={item.get('remote_path')} "
            f"error={item.get('error')}",
            flush=True,
        )
    if failed > 0:
        return 4
    return 0


def _sync_schema_and_models(
    *,
    host: str,
    port: int,
    timeout: float = DEFAULT_SUBMIT_TIMEOUT,
    start_timeout: float = DEFAULT_START_TIMEOUT,
    write_report: bool = True,
) -> dict[str, Any]:
    ensure_server_running(host=host, port=port, timeout=start_timeout)
    engine = _build_sql_engine(argparse.Namespace(host=host, port=port))
    try:
        schema_result = engine.execute_sql(
            sql="REFRESH SCHEMA;",
            compile_only=True,
            no_cache=False,
            timeout=timeout,
            statement_index=1,
        )
        models_result = engine.execute_sql(
            sql="SELECT name FROM models;",
            compile_only=True,
            no_cache=False,
            timeout=timeout,
            statement_index=2,
        )
    except SQLEngineError as exc:
        raise CliError(str(exc), exit_code=exc.exit_code) from exc

    rows = models_result.get("rows", [])
    categories = sorted(
        {
            str(row.get("category"))
            for row in rows
            if isinstance(row, dict) and row.get("category") is not None
        }
    )

    report = {
        "synced_at": time.time(),
        "scheme": _HTTP_SCHEME,
        "host": host,
        "port": port,
        "schema_tables": schema_result.get("tables"),
        "models_count": len(rows),
        "categories": categories,
        "remote": _TARGET_REMOTE,
    }
    if write_report:
        report_path = get_state_dir() / "sync_last.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
    return report


def cmd_sync(args: argparse.Namespace) -> int:
    log("syncing nodes and models")
    report = _sync_schema_and_models(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        start_timeout=getattr(args, "start_timeout", DEFAULT_START_TIMEOUT),
        write_report=True,
    )

    print(
        f"sync_done schema_tables={report['schema_tables']} "
        f"models={report['models_count']} "
        f"categories={len(report.get('categories', []))} "
        f"report={report.get('report_path', '')}",
        flush=True,
    )
    return 0


def cmd_config_init(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve() if args.path else (_find_workspace_root() / DEFAULT_CONFIG_FILE)
    if path.exists() and not args.force:
        raise CliError(f"Config already exists: {path} (use --force to overwrite)", exit_code=2)
    payload = _build_default_config_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"config_written path={path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comfy-agent", description="Custom Comfy server CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    status_cmd = sub.add_parser("status", help="Show target server status (remote-only)")
    status_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    status_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    status_cmd.add_argument("--host", default=DEFAULT_HOST)
    status_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    status_cmd.set_defaults(func=cmd_status)

    doctor_cmd = sub.add_parser("doctor", help="Run remote server connection diagnostics")
    doctor_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    doctor_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    doctor_cmd.add_argument("--host", default=DEFAULT_HOST)
    doctor_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    doctor_cmd.add_argument("--timeout", type=float, default=5.0)
    doctor_cmd.set_defaults(func=cmd_doctor)

    stop_cmd = sub.add_parser("stop", help="Unsupported in remote-only mode")
    stop_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    stop_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    stop_cmd.add_argument("--host", default=DEFAULT_HOST)
    stop_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    stop_cmd.add_argument("--timeout", type=float, default=10.0, help="Graceful stop timeout in seconds")
    stop_cmd.add_argument("--force", action="store_true", help="Send SIGKILL if graceful stop times out")
    stop_cmd.set_defaults(func=cmd_stop)

    restart_cmd = sub.add_parser("restart", help="Unsupported in remote-only mode")
    restart_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    restart_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    restart_cmd.add_argument("--host", default=DEFAULT_HOST)
    restart_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    restart_cmd.add_argument("--stop-timeout", type=float, default=10.0, help="Graceful stop timeout in seconds")
    restart_cmd.add_argument("--start-timeout", type=float, default=DEFAULT_START_TIMEOUT)
    restart_cmd.add_argument("--force", action="store_true", help="Send SIGKILL if graceful stop times out")
    restart_cmd.set_defaults(func=cmd_restart)

    pull_cmd = sub.add_parser("pull", help="Pull models from Hugging Face using local config")
    pull_cmd.add_argument("--config", help=f"HF pull config JSON path (default: ./hf_pull_config.json)")
    pull_cmd.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    pull_cmd.add_argument("--dry-run", action="store_true", help="Show actions without writing files")
    pull_cmd.set_defaults(func=cmd_pull)

    copy_assets_cmd = sub.add_parser("copy-assets", help="Copy local assets to remote Comfy input folder via API upload")
    copy_assets_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    copy_assets_cmd.add_argument("source", nargs="?", help="Source file/folder (omit with --all)")
    copy_assets_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    copy_assets_cmd.add_argument("--host", default=DEFAULT_HOST)
    copy_assets_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    copy_assets_cmd.add_argument("--timeout", type=float, default=DEFAULT_SUBMIT_TIMEOUT)
    copy_assets_cmd.add_argument("--all", action="store_true", help="Copy all files from local ./input/assets")
    copy_assets_cmd.add_argument("--dry-run", action="store_true", help="Show files that would be uploaded")
    copy_assets_cmd.set_defaults(func=cmd_copy_assets)

    sync_cmd = sub.add_parser("sync", help="Sync node schema and model inventory from server")
    sync_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    sync_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    sync_cmd.add_argument("--host", default=DEFAULT_HOST)
    sync_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    sync_cmd.add_argument("--start-timeout", type=float, default=DEFAULT_START_TIMEOUT)
    sync_cmd.add_argument("--timeout", type=float, default=DEFAULT_SUBMIT_TIMEOUT)
    sync_cmd.set_defaults(func=cmd_sync)

    submit_cmd = sub.add_parser("submit", help="Submit workflow JSON")
    submit_cmd.add_argument("workflow", help="Path to API prompt workflow JSON")
    submit_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    submit_cmd.add_argument("--host", default=DEFAULT_HOST)
    submit_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    submit_cmd.add_argument("--timeout", type=float, default=DEFAULT_SUBMIT_TIMEOUT)
    submit_cmd.add_argument("--no-cache", action="store_true", help="Force a fresh run by randomizing seed inputs")
    submit_cmd.add_argument("--skip-validate", action="store_true", help="Skip preflight validate+sync before submit")
    submit_cmd.set_defaults(func=cmd_submit)

    validate_cmd = sub.add_parser("validate", help="Validate workflow JSON using local validator policies")
    validate_cmd.add_argument("workflow", help="Path to workflow JSON (API prompt or UI workflow)")
    validate_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    validate_cmd.add_argument("--host", default=DEFAULT_HOST)
    validate_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    validate_cmd.set_defaults(func=cmd_validate)

    sql_cmd = sub.add_parser("sql", help="Run ComfySQL (dynamic nodes + workflow tables)")
    sql_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    sql_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    sql_cmd.add_argument("--sql", help="ComfySQL statement text")
    sql_cmd.add_argument("--sql-file", help="Path to .sql file with one or more statements")
    sql_cmd.add_argument(
        "--show-tables",
        choices=["all", "workflows", "templates", "nodes", "presets", "profiles", "models"],
        help="Shortcut for SHOW TABLES with optional filtering",
    )
    sql_cmd.add_argument("--compile-only", action="store_true", help="Compile SQL without submitting to server")
    sql_cmd.add_argument("--dry-run", action="store_true", help="Alias for --compile-only (no submit).")
    sql_cmd.add_argument("--host", default=DEFAULT_HOST)
    sql_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    sql_cmd.add_argument("--timeout", type=float, default=DEFAULT_SUBMIT_TIMEOUT)
    sql_cmd.add_argument("--no-cache", action="store_true", help="Force a fresh run by randomizing seed inputs")
    sql_cmd.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts for destructive SQL")
    sql_cmd.add_argument(
        "--upload-mode",
        choices=["strict", "warn", "off"],
        default="strict",
        help="SQL asset auto-upload behavior before SELECT submit.",
    )
    sql_cmd.add_argument(
        "--download-output",
        action="store_true",
        help="After successful SELECT submit, download generated output files locally.",
    )
    sql_cmd.add_argument(
        "--output-mode",
        choices=["none", "download"],
        help="Output handling mode for SELECT: none (default) or download.",
    )
    sql_cmd.add_argument(
        "--download-dir",
        help="Local folder to save downloaded outputs (default: ./output).",
    )
    sql_cmd.set_defaults(func=cmd_sql)

    config_cmd = sub.add_parser("config", help="Manage comfy-agent config")
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)
    config_init = config_sub.add_parser("init", help="Write a starter config file")
    config_init.add_argument("--path", help=f"Output path (default: ./{DEFAULT_CONFIG_FILE})")
    config_init.add_argument("--force", action="store_true", help="Overwrite if file exists")
    config_init.set_defaults(func=cmd_config_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) not in {"config", "pull"}:
        _apply_connection_settings(args)
    try:
        return int(args.func(args))
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        # Respect Ctrl-C for foreground command control.
        if signal.getsignal(signal.SIGINT) is not None:
            print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
