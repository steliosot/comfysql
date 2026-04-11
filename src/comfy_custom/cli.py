from __future__ import annotations

import atexit
import argparse
import copy
import contextlib
import json
import os
import random
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import websocket
from comfy_custom.http_auth import urlopen_with_auth_fallback
from comfy_custom.sql_engine import LocalComfySQLEngine, SQLEngineError
from comfy_custom.terminal_ui import TerminalUI


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8188
DEFAULT_START_TIMEOUT = 300.0
DEFAULT_SUBMIT_TIMEOUT = 600.0
EXIT_PARSE = 2
EXIT_AUTH = 3
EXIT_NETWORK = 4
EXIT_VALIDATION = 5
EXIT_RUNTIME = 6
PRIMARY_CONFIG_FILE = "comfysql.json"
LEGACY_CONFIG_FILE = "comfy-agent.json"
DEFAULT_CONFIG_FILE = PRIMARY_CONFIG_FILE
_UI: TerminalUI | None = None
_REQUEST_HEADERS: dict[str, str] = {}
_HTTP_SCHEME = "http"
_WS_SCHEME = "ws"
_TARGET_REMOTE = False
_LEGACY_CONFIG_HINT_SHOWN = False
_OUTPUT_FORMAT = "text"


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
    if _OUTPUT_FORMAT == "json":
        return
    _ui().info(f"[comfy-agent] {message}")


def _error_hint_for_message(message: str) -> str | None:
    text = str(message or "").strip().lower()
    if not text:
        return None

    if "unknown server alias" in text or "config has no 'servers' map" in text:
        return "Run `comfysql config init` and then `comfysql status <alias>`."
    if "comfy_url/config server.url" in text or "config already exists" in text:
        return f"Check `{DEFAULT_CONFIG_FILE}` and run `comfysql status remote`."
    if "timed out waiting for server" in text or "connection failed" in text or "nodename nor servname provided" in text:
        return "Run `comfysql doctor <server>` to check connectivity and auth."
    if "workflow file not found" in text or "missing workflow" in text:
        return "Run `comfysql sql <server> --sql \"SHOW TABLES workflows;\"`."
    if "missing preset" in text or "unknown preset" in text:
        return "Run `SHOW PRESETS;` or create one with `CREATE PRESET <name> FOR <workflow> WITH ...;`."
    if "missing profile" in text or "unknown profile" in text:
        return "Run `SHOW PROFILES;` or create one with `CREATE PROFILE <name> WITH ...;`."
    if "character" in text and ("missing" in text or "unknown" in text or "not found" in text):
        return "Run `SHOW CHARACTERS;` then `DESCRIBE CHARACTER <name>;`."
    if "object" in text and ("missing" in text or "unknown" in text or "not found" in text):
        return "Run `SHOW OBJECTS;` then `DESCRIBE OBJECT <name>;`."
    if "slot" in text and ("missing" in text or "unknown" in text or "not found" in text):
        return "Create a binding with `CREATE SLOT <slot> FOR <workflow> AS CHARACTER|OBJECT BINDING <node.input>;`."
    if "sql parse failed" in text or "unsupported sql statement" in text:
        return "Try `EXPLAIN SELECT ...;` and use ';' at the end for multiline SQL."
    if "confirmation required for state-changing sql" in text:
        return "Re-run with `-y` for non-interactive execution."
    if "unknown table/node" in text:
        return "Run `SHOW TABLES;` or `SHOW TABLES nodes;` and retry with a valid name."
    if "upload_failed" in text or "copy_failed" in text:
        return "Retry with `comfysql copy-assets <server> --all` and verify `comfysql doctor <server>`."
    if "download_failed" in text:
        return "Use a unique `filename_prefix` in WHERE, then retry with `--download-output`."
    if "missing model" in text or "models" in text and "failed" in text:
        return "Run `comfysql sync <server>` and then `SHOW MODELS;`."
    return None


def _print_error_with_hint(message: str, *, to_stderr: bool = False) -> None:
    target = sys.stderr if to_stderr else sys.stdout
    print(message, file=target, flush=True)
    hint = _error_hint_for_message(message)
    if hint:
        print(f"hint: {hint}", file=target, flush=True)


def _wants_json(args: argparse.Namespace) -> bool:
    return str(getattr(args, "output", "text") or "text").strip().lower() == "json"


def _set_output_mode(args: argparse.Namespace) -> None:
    global _OUTPUT_FORMAT
    _OUTPUT_FORMAT = "json" if _wants_json(args) else "text"


def _emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _capture_stdout_call(func, *args, **kwargs):
    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        result = func(*args, **kwargs)
    events = [line for line in buf.getvalue().splitlines() if line.strip()]
    return result, events


def _normalized_error_exit_code(message: str, original_code: int | None = None) -> int:
    if original_code == 130:
        return 130
    text = str(message or "").strip().lower()
    if not text:
        return EXIT_RUNTIME

    parse_markers = (
        "unsupported sql statement",
        "sql parse failed",
        "invalid report syntax",
        "no sql statements found",
        "config file must be a json object",
        "invalid config json",
        "unknown server alias",
        "use either --sql or --sql-file",
        "missing workflow path",
        "not found:",
    )
    auth_markers = ("401", "403", "unauthorized", "forbidden", "auth header", "invalid token")
    network_markers = (
        "timed out waiting for server",
        "connection failed",
        "websocket connection failed",
        "urlopen error",
        "nodename nor servname provided",
        "failed to fetch history",
        "download_failed",
    )
    validation_markers = (
        "validation_failed",
        "validation failed",
        "missing preset",
        "missing profile",
        "unknown preset",
        "unknown profile",
        "unknown workflow table",
    )

    if any(marker in text for marker in parse_markers):
        return EXIT_PARSE
    if any(marker in text for marker in auth_markers):
        return EXIT_AUTH
    if any(marker in text for marker in network_markers):
        return EXIT_NETWORK
    if any(marker in text for marker in validation_markers):
        return EXIT_VALIDATION
    if original_code in {EXIT_PARSE, EXIT_AUTH, EXIT_NETWORK, EXIT_VALIDATION, EXIT_RUNTIME}:
        return int(original_code)
    return EXIT_RUNTIME


def _emit_json_error(message: str, *, original_exit_code: int | None = None) -> int:
    normalized = _normalized_error_exit_code(message, original_code=original_exit_code)
    payload: dict[str, Any] = {
        "status": "error",
        "error": str(message),
        "exit_code": normalized,
    }
    hint = _error_hint_for_message(message)
    if hint:
        payload["hint"] = hint
    _emit_json(payload)
    return normalized


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
    global _LEGACY_CONFIG_HINT_SHOWN
    raw = getattr(args, "config", None)
    if raw:
        return Path(raw).expanduser().resolve()
    workspace = _find_workspace_root()
    primary = (workspace / PRIMARY_CONFIG_FILE).resolve()
    if primary.exists():
        return primary
    legacy = (workspace / LEGACY_CONFIG_FILE).resolve()
    if legacy.exists():
        if not _LEGACY_CONFIG_HINT_SHOWN and _OUTPUT_FORMAT != "json":
            _ui().hint(
                f"Using legacy config `{LEGACY_CONFIG_FILE}`. "
                f"Run `comfysql config init --path ./{PRIMARY_CONFIG_FILE}` to migrate."
            )
            _LEGACY_CONFIG_HINT_SHOWN = True
        return legacy
    return primary


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
    host_alias_selected = False
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
    else:
        cli_host_candidate = str(getattr(args, "host", DEFAULT_HOST) or "").strip()
        alias_candidate = cli_host_candidate.split(":", 1)[0].strip()
        maybe_alias_cfg = servers_cfg.get(alias_candidate)
        if alias_candidate and isinstance(maybe_alias_cfg, dict):
            selected_server_cfg = maybe_alias_cfg
            host_alias_selected = True
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

    if resolved_url and (using_cli_defaults or host_alias_selected):
        parsed_scheme, parsed_host, parsed_port = _parse_url(resolved_url)
        scheme, host, port = parsed_scheme, parsed_host, parsed_port

    token = str(os.environ.get("COMFY_AUTH_HEADER") or auth_cfg.get("token") or "").strip()
    header_name = str(os.environ.get("COMFY_AUTH_HEADER_NAME") or auth_cfg.get("header_name") or "Authorization").strip()
    auth_scheme = str(os.environ.get("COMFY_AUTH_SCHEME") or auth_cfg.get("scheme") or "Bearer").strip()
    headers: dict[str, str] = {}
    if token:
        headers[header_name] = f"{auth_scheme} {token}".strip() if auth_scheme else token

    remote = host not in {"127.0.0.1", "localhost", "::1"}
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
            (workspace / "comfyui-core").resolve(),
            (workspace / "comfy-custom" / "comfyui-core").resolve(),
            (workspace / "comfy_files").resolve(),
        ]
        data_dir = next((p for p in candidates if _looks_like_comfy_data_dir(p)), workspace.resolve())

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

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is not None:
            buf.append(ch)
            # Support backslash-escaped quote chars in SQL strings.
            if ch == "\\" and i + 1 < n:
                i += 1
                buf.append(text[i])
                i += 1
                continue
            # Support doubled quote escaping ('' / "").
            if ch == quote and i + 1 < n and text[i + 1] == quote:
                i += 1
                buf.append(text[i])
                i += 1
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", "\""):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement + ";")
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1

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
    nodes_preview_limit = 12
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
    if action == "create_character":
        print(f"character_created name={result.get('character_name')} image={result.get('image_name')}", flush=True)
        return
    if action == "create_object":
        print(f"object_created name={result.get('object_name')} image={result.get('image_name')}", flush=True)
        return
    if action == "create_slot":
        print(
            f"slot_created workflow={result.get('workflow_table')} slot={result.get('slot_name')} "
            f"kind={result.get('slot_kind')} binding={result.get('binding_key')}",
            flush=True,
        )
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
    if action == "show_characters":
        rows = result.get("rows", [])
        print(f"characters_count={len(rows)}", flush=True)
        for row in rows:
            name = row.get("name")
            workflows = row.get("workflow_count", 0)
            bindings = row.get("binding_count", 0)
            print(f"- {name} workflows={workflows} bindings={bindings}", flush=True)
        return
    if action == "show_objects":
        rows = result.get("rows", [])
        print(f"objects_count={len(rows)}", flush=True)
        for row in rows:
            name = row.get("name")
            workflows = row.get("workflow_count", 0)
            bindings = row.get("binding_count", 0)
            print(f"- {name} workflows={workflows} bindings={bindings}", flush=True)
        return
    if action in {"describe_character", "describe_object"}:
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
                        f"- {row.get('table')} (intent={row.get('intent', '-')}, signature={row.get('signature', '-')})",
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
            if table_filter == "nodes":
                for row in nodes:
                    table = row.get("table")
                    category = row.get("category", "")
                    print(f"- {table} (category={category})", flush=True)
            else:
                preview = nodes[:nodes_preview_limit]
                for row in preview:
                    table = row.get("table")
                    category = row.get("category", "")
                    print(f"- {table} (category={category})", flush=True)
                hidden = max(0, len(nodes) - len(preview))
                if hidden > 0:
                    print(
                        f"- ... ({hidden} more nodes hidden). Run `SHOW TABLES nodes;` to view all.",
                        flush=True,
                    )
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
        resolved_layers = result.get("resolved_layers")
        if isinstance(resolved_layers, dict):
            preset = str(resolved_layers.get("preset", "") or "")
            character = str(resolved_layers.get("character", "") or "")
            obj = str(resolved_layers.get("object", "") or "")
            profile = str(resolved_layers.get("profile", "") or "")
            print(
                f"resolved preset={preset or '-'} character={character or '-'} object={obj or '-'} profile={profile or '-'}",
                flush=True,
            )
            hint = str(resolved_layers.get("hint", "") or "").strip()
            if hint:
                print(f"hint: {hint}", flush=True)
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
        resolved_layers = result.get("resolved_layers")
        if isinstance(resolved_layers, dict):
            preset = str(resolved_layers.get("preset", "") or "")
            character = str(resolved_layers.get("character", "") or "")
            obj = str(resolved_layers.get("object", "") or "")
            profile = str(resolved_layers.get("profile", "") or "")
            print(
                f"resolved preset={preset or '-'} character={character or '-'} object={obj or '-'} profile={profile or '-'}",
                flush=True,
            )
            hint = str(resolved_layers.get("hint", "") or "").strip()
            if hint:
                print(f"hint: {hint}", flush=True)
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
    nodes_preview_limit = 12
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
    if action in {"describe_preset", "describe_profile", "describe_character", "describe_object", "describe"}:
        ui.print_json(result)
        return
    if action == "show_characters":
        rows = result.get("rows", [])
        ui.line(f"[bold cyan]characters[/] count={len(rows)}")
        ui.print_table(
            "CHARACTERS",
            ["name", "workflows", "bindings"],
            [
                [
                    str(r.get("name", "")),
                    str(r.get("workflow_count", 0)),
                    str(r.get("binding_count", 0)),
                ]
                for r in rows
            ],
        )
        return
    if action == "show_objects":
        rows = result.get("rows", [])
        ui.line(f"[bold cyan]objects[/] count={len(rows)}")
        ui.print_table(
            "OBJECTS",
            ["name", "workflows", "bindings"],
            [
                [
                    str(r.get("name", "")),
                    str(r.get("workflow_count", 0)),
                    str(r.get("binding_count", 0)),
                ]
                for r in rows
            ],
        )
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
                ["name", "intent", "signature"],
                [
                    [
                        str(r.get("table", "")),
                        str(r.get("intent", "-")),
                        str(r.get("signature", "-")),
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
            if table_filter == "nodes":
                node_rows = nodes
            else:
                node_rows = nodes[:nodes_preview_limit]
            ui.print_table(
                "NODES",
                ["class_type", "category"],
                [[str(r.get("table", "")), str(r.get("category", ""))] for r in node_rows],
            )
            if table_filter != "nodes" and len(nodes) > len(node_rows):
                ui.line(
                    f"[dim]... ({len(nodes) - len(node_rows)} more nodes hidden). "
                    "Run `SHOW TABLES nodes;` to view all.[/]"
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
        resolved_layers = result.get("resolved_layers")
        if isinstance(resolved_layers, dict):
            preset = str(resolved_layers.get("preset", "") or "")
            character = str(resolved_layers.get("character", "") or "")
            obj = str(resolved_layers.get("object", "") or "")
            profile = str(resolved_layers.get("profile", "") or "")
            ui.line(
                "[bold cyan]resolved[/] "
                f"preset={preset or '-'} character={character or '-'} object={obj or '-'} profile={profile or '-'}"
            )
            hint = str(resolved_layers.get("hint", "") or "").strip()
            if hint:
                ui.line(f"[yellow]hint[/] {hint}")
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
        resolved_layers = result.get("resolved_layers")
        if isinstance(resolved_layers, dict):
            preset = str(resolved_layers.get("preset", "") or "")
            character = str(resolved_layers.get("character", "") or "")
            obj = str(resolved_layers.get("object", "") or "")
            profile = str(resolved_layers.get("profile", "") or "")
            ui.line(
                "[bold cyan]resolved[/] "
                f"preset={preset or '-'} character={character or '-'} object={obj or '-'} profile={profile or '-'}"
            )
            hint = str(resolved_layers.get("hint", "") or "").strip()
            if hint:
                ui.line(f"[yellow]hint[/] {hint}")
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
    upper = " ".join(text.upper().split())
    if not upper:
        return False

    mutating_prefixes = (
        "DROP ",
        "DELETE ",
        "TRUNCATE ",
        "ALTER ",
        "CREATE TABLE ",
        "CREATE TEMPLATE ",
        "CREATE PRESET ",
        "CREATE PROFILE ",
        "CREATE CHARACTER ",
        "CREATE OBJECT ",
        "CREATE SLOT ",
        "CREATE QUERY ",
        "SET META FOR ",
        "UNSET META FOR ",
        "RUN QUERY ",
    )
    return upper.startswith(mutating_prefixes)


def _confirm_sql_if_needed(sql_text: str, yes: bool) -> None:
    if yes or not _is_destructive_sql(sql_text):
        return
    try:
        answer = input("This statement can change state. Continue? [y/N]: ").strip().lower()
    except EOFError as exc:
        raise CliError("Confirmation required for state-changing SQL in non-interactive mode. Re-run with -y.", exit_code=2) from exc
    if answer not in {"y", "yes"}:
        raise CliError("Cancelled by user.", exit_code=130)


def _confirm_non_sql_mutation_if_needed(*, yes: bool, prompt: str) -> None:
    if yes:
        return
    try:
        answer = input(f"{prompt} Continue? [y/N]: ").strip().lower()
    except EOFError as exc:
        raise CliError("Confirmation required for mutating command in non-interactive mode. Re-run with --yes.", exit_code=2) from exc
    if answer not in {"y", "yes"}:
        raise CliError("Cancelled by user.", exit_code=130)


def _execute_sql_statement(engine: LocalComfySQLEngine, sql_text: str, args: argparse.Namespace, statement_index: int) -> None:
    report_spec = _parse_report_sql(sql_text)
    if report_spec is not None:
        inner_sql, report_path = report_spec
        _confirm_sql_if_needed(sql_text=inner_sql, yes=bool(getattr(args, "yes", False)))
        _run_sql_report(
            engine=engine,
            sql_text=inner_sql,
            args=args,
            report_path=Path(report_path).expanduser().resolve(),
            title=str(getattr(args, "title", "") or "SQL Run Report"),
            extra_images=[],
        )
        return
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
    except Exception as exc:
        raise CliError(f"SQL execution failed unexpectedly: {exc}", exit_code=4) from exc
    _render_sql_result(result, table_filter=getattr(args, "show_tables", "all") or "all")


def _is_complete_sql_statement(sql_text: str) -> bool:
    text = sql_text.strip()
    if not text:
        return False
    try:
        from comfy_custom.comfysql_runner.sql_parser import SQLParseError, parse_sql

        parse_sql(text)
        return True
    except SQLParseError:
        return False
    except Exception:
        return False


def _should_auto_execute_without_semicolon(*, sql_text: str, buffered_line_count: int) -> bool:
    # In interactive mode we keep semicolon-optional for one-liners, but require
    # an explicit ';' for multi-line input to avoid accidental early execution.
    if buffered_line_count > 1:
        return False
    return _is_complete_sql_statement(sql_text)

SQL_ASCII_ART = "\n".join(
    [
        "▄▖     ▐▘  ▄▖▄▖▖ ",
        "▌ ▛▌▛▛▌▜▘▌▌▚ ▌▌▌ ",
        "▙▖▙▌▌▌▌▐ ▙▌▄▌█▌▙▖",
        "         ▄▌   ▘  ",
    ]
)


def _run_sql_terminal(args: argparse.Namespace, engine: LocalComfySQLEngine) -> int:
    _setup_sql_readline_history()
    print(SQL_ASCII_ART, flush=True)
    print("ComfySQL terminal. Semicolon ';' is optional. Type '.exit' or '.quit' to leave.", flush=True)
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
                _print_error_with_hint(str(exc))
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
                _print_error_with_hint(str(exc))
            statement_index += 1
            buf = []
        else:
            if _should_auto_execute_without_semicolon(sql_text=last, buffered_line_count=len(buf)):
                try:
                    _execute_sql_statement(
                        engine=engine,
                        sql_text=last,
                        args=args,
                        statement_index=statement_index,
                    )
                except CliError as exc:
                    _print_error_with_hint(str(exc))
                statement_index += 1
                buf = []
            else:
                buf = [last]


SQL_TERMINAL_HINTS = [
    "SELECT",
    "EXPLAIN",
    "DESCRIBE",
    "CREATE CHARACTER",
    "CREATE OBJECT",
    "CREATE SLOT",
    "SHOW CHARACTERS",
    "SHOW OBJECTS",
    "DESCRIBE CHARACTER",
    "DESCRIBE OBJECT",
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
    _ui().section(f"start server={args.host}:{args.port}")
    state = start_server(host=args.host, port=args.port, timeout=args.start_timeout)
    _ui().success(
        f"server_started pid={state.pid} host={state.host} port={state.port} log={state.log_path}",
    )
    if not _REQUEST_HEADERS:
        log("no auth header configured (ok if server is public)")
    models_dir = get_comfy_data_dir() / "models"
    if not _has_synced_models(models_dir):
        _ui().warning(
            "no synced models found under models/. "
            "Run `comfysql pull --yes` to sync defaults, or use your own model files."
        )
    _ui().success(f"server_healthy host={args.host} port={args.port}")
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    server_or_workflow = str(getattr(args, "server_or_workflow", "") or "").strip()
    workflow_arg = str(getattr(args, "workflow", "") or "").strip()
    if workflow_arg:
        args.server = server_or_workflow
        workflow_value = workflow_arg
    else:
        workflow_value = server_or_workflow
    if not workflow_value:
        raise CliError("Missing workflow path. Usage: comfysql submit [server] <workflow.json>", exit_code=2)
    workflow_path = Path(workflow_value).expanduser().resolve()
    _ui().section(f"submit workflow={workflow_path.name} server={args.host}:{args.port}")
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
    _ui().success("submit_done")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    server_or_workflow = str(getattr(args, "server_or_workflow", "") or "").strip()
    workflow_arg = str(getattr(args, "workflow", "") or "").strip()
    if workflow_arg:
        args.server = server_or_workflow
        workflow_value = workflow_arg
    else:
        workflow_value = server_or_workflow
    if not workflow_value:
        raise CliError("Missing workflow path. Usage: comfysql validate [server] <workflow.json>", exit_code=2)
    _ui().section(f"validate server={args.host}:{args.port}")
    return validate_workflow(
        workflow_path=Path(workflow_value).expanduser().resolve(),
        host=args.host,
        port=args.port,
    )


def cmd_sql(args: argparse.Namespace) -> int:
    json_mode = _wants_json(args)
    if not json_mode:
        _ui().section(f"sql server={args.host}:{args.port}")
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

    if json_mode:
        rows: list[dict[str, Any]] = []
        for index, statement in enumerate(statements, start=1):
            report_spec = _parse_report_sql(statement)
            if report_spec is not None:
                inner_sql, report_path = report_spec
                _confirm_sql_if_needed(sql_text=inner_sql, yes=bool(getattr(args, "yes", False)))
                report_result, events = _capture_stdout_call(
                    _run_sql_report,
                    engine=engine,
                    sql_text=inner_sql,
                    args=args,
                    report_path=Path(report_path).expanduser().resolve(),
                    title=str(getattr(args, "title", "") or "SQL Run Report"),
                    extra_images=[],
                )
                rows.append(
                    {
                        "statement_index": index,
                        "statement": statement,
                        "kind": "report",
                        "report_path": str(Path(report_path).expanduser().resolve()),
                        "result": report_result,
                        "events": events,
                    }
                )
                continue
            _confirm_sql_if_needed(sql_text=statement, yes=bool(getattr(args, "yes", False)))
            try:
                result, events = _capture_stdout_call(
                    engine.execute_sql,
                    sql=statement,
                    compile_only=args.compile_only,
                    no_cache=args.no_cache,
                    timeout=args.timeout,
                    statement_index=index,
                    download_output=bool(getattr(args, "download_output", False)),
                    download_dir=getattr(args, "download_dir", None),
                    upload_mode=str(getattr(args, "upload_mode", "strict")),
                )
            except SQLEngineError as exc:
                raise CliError(str(exc), exit_code=exc.exit_code) from exc
            rows.append(
                {
                    "statement_index": index,
                    "statement": statement,
                    "kind": "sql",
                    "result": result,
                    "events": events,
                }
            )
        _emit_json({"status": "ok", "server": f"{args.host}:{args.port}", "statements": rows})
        return 0

    for index, statement in enumerate(statements, start=1):
        _execute_sql_statement(
            engine=engine,
            sql_text=statement,
            args=args,
            statement_index=index,
        )
    return 0


def _path_for_markdown(path: Path, *, report_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(report_dir.resolve())).replace("\\", "/")
    except Exception:
        return str(path.resolve())


def _parse_report_sql(sql_text: str) -> tuple[str, str] | None:
    text = str(sql_text or "").strip()
    if not text:
        return None
    normalized = text.rstrip().rstrip(";").strip()
    if not normalized.lower().startswith("report "):
        return None
    body = normalized[7:].strip()
    if not body:
        return None

    quote: str | None = None
    to_positions: list[int] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if quote is not None:
            if ch == "\\" and i + 1 < len(body):
                i += 2
                continue
            if ch == quote and i + 1 < len(body) and body[i + 1] == quote:
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", "\""):
            quote = ch
            i += 1
            continue
        if i + 1 < len(body) and body[i : i + 2].lower() == "to":
            prev_ok = i == 0 or body[i - 1].isspace()
            next_ok = i + 2 == len(body) or body[i + 2].isspace()
            if prev_ok and next_ok:
                to_positions.append(i)
            i += 2
            continue
        i += 1

    if not to_positions:
        return None
    to_index = to_positions[-1]
    inner_sql = body[:to_index].strip()
    raw_path = body[to_index + 2 :].strip()
    if (raw_path.startswith("'") and raw_path.endswith("'")) or (raw_path.startswith('"') and raw_path.endswith('"')):
        raw_path = raw_path[1:-1]
    if not inner_sql or not raw_path:
        raise CliError("Invalid REPORT syntax. Use: REPORT <SQL> TO '<path.md>';", exit_code=2)
    return inner_sql, raw_path


def _run_sql_report(
    *,
    engine: LocalComfySQLEngine,
    sql_text: str,
    args: argparse.Namespace,
    report_path: Path,
    title: str,
    extra_images: list[str],
) -> int:
    from comfy_custom.comfysql_runner.sql_parser import SelectQuery, parse_sql

    start = time.monotonic()
    try:
        result = engine.execute_sql(
            sql=sql_text,
            compile_only=bool(getattr(args, "compile_only", False)),
            no_cache=bool(getattr(args, "no_cache", False)),
            timeout=float(getattr(args, "timeout", DEFAULT_SUBMIT_TIMEOUT)),
            statement_index=1,
            download_output=bool(getattr(args, "download_output", True)),
            download_dir=getattr(args, "download_dir", None),
            upload_mode=str(getattr(args, "upload_mode", "strict")),
        )
    except SQLEngineError as exc:
        raise CliError(str(exc), exit_code=exc.exit_code) from exc
    elapsed = time.monotonic() - start

    parsed = parse_sql(sql_text)
    table_name = ""
    preset_name = ""
    character_name = ""
    object_name = ""
    profile_name = ""
    if isinstance(parsed, SelectQuery):
        table_name = parsed.table_name
        preset_name = str(parsed.preset_name or "")
        character_name = str(parsed.character_name or "")
        object_name = str(getattr(parsed, "object_name", "") or "")
        profile_name = str(parsed.profile_name or "")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded_outputs = result.get("downloaded_outputs", []) if isinstance(result, dict) else []
    images: list[Path] = []
    for item in downloaded_outputs if isinstance(downloaded_outputs, list) else []:
        p = Path(str(item)).expanduser().resolve()
        if p.exists():
            images.append(p)
    for manual in extra_images:
        p = Path(str(manual)).expanduser().resolve()
        if p.exists() and p not in images:
            images.append(p)

    lines: list[str] = []
    lines.append(f"# {title or 'SQL Run Report'}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Server: `{args.host}:{args.port}`")
    lines.append(f"- Duration: `{elapsed:.2f}s`")
    if table_name:
        lines.append(f"- Table: `{table_name}`")
    if preset_name:
        lines.append(f"- Preset: `{preset_name}`")
    if character_name:
        lines.append(f"- Character: `{character_name}`")
    if object_name:
        lines.append(f"- Object: `{object_name}`")
    if profile_name:
        lines.append(f"- Profile: `{profile_name}`")
    if isinstance(result, dict) and isinstance(result.get("api_prompt_path"), str):
        lines.append(f"- API Prompt: `{result.get('api_prompt_path')}`")
    lines.append(f"- Downloaded Outputs: `{len(images)}`")
    lines.append("")
    lines.append("## SQL")
    lines.append("```sql")
    lines.append(sql_text.strip())
    lines.append("```")
    lines.append("")
    lines.append("## Images")
    if images:
        for img in images:
            md_path = _path_for_markdown(img, report_dir=report_path.parent)
            lines.append(f"![{img.name}]({md_path})")
            lines.append("")
    else:
        lines.append("No images were available.")
        lines.append("")
    lines.append("## Raw Result")
    lines.append("```json")
    lines.append(json.dumps(result if isinstance(result, dict) else {"result": result}, indent=2, ensure_ascii=True))
    lines.append("```")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    _ui().success(f"report_written path={report_path} duration_s={elapsed:.2f} images={len(images)}")
    return 0


def cmd_sql_report(args: argparse.Namespace) -> int:
    from comfy_custom.comfysql_runner.sql_parser import SelectQuery, parse_sql

    json_mode = _wants_json(args)
    if not json_mode:
        _ui().section(f"sql-report server={args.host}:{args.port}")
    engine = _build_sql_engine(args)
    sql_raw = getattr(args, "sql", None)
    if sql_raw and args.sql_file:
        raise CliError("Use either --sql or --sql-file, not both.", exit_code=2)
    if args.sql_file:
        sql_path = Path(args.sql_file).expanduser().resolve()
        if not sql_path.exists():
            raise CliError(f"SQL file not found: {sql_path}", exit_code=2)
        sql_raw = sql_path.read_text(encoding="utf-8")
    if not sql_raw:
        raise CliError("Provide --sql or --sql-file for sql-report.", exit_code=2)

    statements = _split_sql_statements(sql_raw)
    if not statements:
        raise CliError("No SQL statements found.", exit_code=2)
    if len(statements) != 1:
        raise CliError("sql-report expects exactly one SQL statement.", exit_code=2)
    sql_text = statements[0]
    report_path = Path(getattr(args, "report", "") or "").expanduser().resolve() if getattr(args, "report", None) else (
        (Path.cwd() / "reports" / f"sql_run_{int(time.time())}.md").resolve()
    )
    title = str(getattr(args, "title", "") or "").strip() or "SQL Run Report"
    extra_images = [str(x) for x in (getattr(args, "image", None) or [])]
    if json_mode:
        rc, events = _capture_stdout_call(
            _run_sql_report,
            engine=engine,
            sql_text=sql_text,
            args=args,
            report_path=report_path,
            title=title,
            extra_images=extra_images,
        )
        _emit_json(
            {
                "status": "ok" if int(rc) == 0 else "error",
                "server": f"{args.host}:{args.port}",
                "report_path": str(report_path),
                "sql": sql_text,
                "events": events,
            }
        )
        return int(rc)
    return _run_sql_report(
        engine=engine,
        sql_text=sql_text,
        args=args,
        report_path=report_path,
        title=title,
        extra_images=extra_images,
    )


def cmd_status(args: argparse.Namespace) -> int:
    healthy = is_server_healthy(args.host, args.port, timeout=1.5)
    if _wants_json(args):
        _emit_json({"status": "ok", "healthy": bool(healthy), "server": f"{args.host}:{args.port}"})
        return 0
    if healthy:
        _ui().success(f"status=running_remote host={args.host} port={args.port}")
    else:
        _ui().warning(f"status=stopped_remote host={args.host} port={args.port}")
        _ui().hint(f"Run `comfysql doctor {args.host}` or `comfysql status remote`.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    json_mode = _wants_json(args)
    if not json_mode:
        _ui().section(f"doctor server={args.host}:{args.port}")
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

    if bool(getattr(args, "full", False)):
        try:
            config_path = _resolve_config_path(args)
            checks.append(("config", config_path.exists(), f"path={config_path}"))
        except Exception as exc:
            checks.append(("config", False, str(exc)))
        assets_dir = _default_assets_dir()
        checks.append(("local_assets_dir", assets_dir.exists(), f"path={assets_dir}"))
        try:
            engine = _build_sql_engine(args)
            engine.execute_sql(
                sql="SHOW TABLES;",
                compile_only=True,
                no_cache=False,
                timeout=max(timeout, 10.0),
                statement_index=1,
            )
            checks.append(("sql_show_tables", True, "ok"))
        except Exception as exc:
            checks.append(("sql_show_tables", False, str(exc)))

    failed = 0
    for name, ok, detail in checks:
        if not ok:
            failed += 1
        if json_mode:
            continue
        status = "ok" if ok else "fail"
        if ok:
            _ui().success(f"doctor {name}={status} detail={detail}")
        else:
            _ui().error(f"doctor {name}={status} detail={detail}")

    if json_mode:
        _emit_json(
            {
                "status": "ok" if failed == 0 else "fail",
                "server": f"{args.host}:{args.port}",
                "checks": [
                    {"name": name, "ok": bool(ok), "detail": detail}
                    for name, ok, detail in checks
                ],
                "failed_checks": failed,
            }
        )
        return 0 if failed == 0 else EXIT_NETWORK

    if failed:
        _ui().error(f"doctor_summary status=fail failed_checks={failed}")
        _ui().hint(f"Run `comfysql status {args.host}` after fixing connectivity/auth.")
        return EXIT_NETWORK
    _ui().success("doctor_summary status=ok failed_checks=0")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    config_path = Path(getattr(args, "config", None) or (_find_workspace_root() / "hf_pull_config.json")).expanduser().resolve()
    workspace = _find_workspace_root().resolve()
    try:
        models_base = get_comfy_data_dir()
    except CliError:
        # Keep pull usable when comfy core is absent but data folders still exist/will be created.
        models_base = workspace
    models_dir = (models_base / "models").resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    try:
        from comfy_custom.hf_pull import PullError, ensure_default_hf_pull_config

        ensure_default_hf_pull_config(config_path)
        report = execute_pull(
            config_path=config_path,
            models_dir=models_dir,
            state_dir=get_state_dir(),
            yes=bool(getattr(args, "yes", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            log_fn=log,
        )
    except PullError as exc:
        raise CliError(str(exc), exit_code=exc.exit_code) from exc

    if report.failed:
        _ui().warning("pull finished with failures")
    else:
        _ui().success("pull finished")
    _ui().line(
        "pull_done "
        f"copied={report.copied} skipped_exists={report.skipped_exists} failed={report.failed} "
        f"bytes_copied={report.bytes_copied} dry_run={'true' if report.dry_run else 'false'}",
    )
    return EXIT_RUNTIME if report.failed else 0


def execute_pull(**kwargs):
    from comfy_custom.hf_pull import execute_pull_hf

    return execute_pull_hf(**kwargs)


def _default_assets_dir() -> Path:
    return (_find_workspace_root() / "input" / "assets").resolve()


def _collect_asset_files(*, source: str | None, all_assets: bool) -> list[Path]:
    if all_assets:
        workspace_root = _find_workspace_root().resolve()
        assets_dir = _default_assets_dir()
        input_dir = (workspace_root / "input").resolve()
        files: list[Path] = []

        # Canonical location: input/assets (supports nested folders).
        if assets_dir.exists() and assets_dir.is_dir():
            files.extend(sorted([p for p in assets_dir.rglob("*") if p.is_file() and not p.name.startswith(".")]))

        # Backward-compatible location: top-level input/ files (excluding hidden files).
        legacy_files: list[Path] = []
        if input_dir.exists() and input_dir.is_dir():
            for entry in sorted(input_dir.iterdir(), key=lambda p: p.name.lower()):
                if entry.is_file() and not entry.name.startswith("."):
                    legacy_files.append(entry)

        # De-duplicate by filename so canonical input/assets wins when both exist.
        seen_names = {p.name for p in files}
        for legacy in legacy_files:
            if legacy.name in seen_names:
                continue
            files.append(legacy)
            seen_names.add(legacy.name)

        if not files:
            raise CliError(
                f"No asset files found in canonical '{assets_dir}' or legacy '{input_dir}'.",
                exit_code=2,
            )
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
    json_mode = _wants_json(args)
    if not json_mode:
        log(
            f"copy_assets host={args.host}:{args.port} files={len(files)} "
            f"dry_run={'true' if args.dry_run else 'false'} mode=http_upload"
        )

    if args.dry_run:
        if json_mode:
            _emit_json(
                {
                    "status": "ok",
                    "server": f"{args.host}:{args.port}",
                    "dry_run": True,
                    "files": [str(f) for f in files],
                }
            )
            return 0
        _ui().section(f"copy-assets dry-run server={args.host}:{args.port}")
        _ui().line(f"copy_assets_plan files={len(files)} mode=http_upload")
        for f in files:
            _ui().line(f"- {f}")
        return 0

    engine = _build_sql_engine(args)
    prompt: dict[str, Any] = {}
    for idx, file_path in enumerate(files, start=1):
        prompt[str(idx)] = {
            "class_type": "LoadImage",
            "inputs": {"image": str(file_path)},
        }

    _confirm_non_sql_mutation_if_needed(
        yes=bool(getattr(args, "yes", False)),
        prompt="This command uploads local assets to the target server.",
    )

    try:
        _patched, report = engine._auto_upload_local_assets(prompt, timeout=float(getattr(args, "timeout", DEFAULT_SUBMIT_TIMEOUT)))
    except SQLEngineError as exc:
        raise CliError(str(exc), exit_code=exc.exit_code) from exc

    uploaded = int(report.get("uploaded_count", 0))
    skipped = int(report.get("skipped_existing_count", 0))
    failed = int(report.get("failed_count", 0))
    if json_mode:
        _emit_json(
            {
                "status": "ok" if failed == 0 else "fail",
                "server": f"{args.host}:{args.port}",
                "uploaded": uploaded,
                "skipped_existing": skipped,
                "failed": failed,
                "failed_items": report.get("failed", []),
            }
        )
        return 0 if failed == 0 else EXIT_RUNTIME
    if failed > 0:
        _ui().warning("copy-assets completed with failures")
    else:
        _ui().success("copy-assets completed")
    _ui().line(f"copy_assets_done uploaded={uploaded} skipped_existing={skipped} failed={failed}")
    for item in report.get("failed", []) or []:
        _ui().error(
            f"- copy_failed local={item.get('local_path')} remote={item.get('remote_path')} "
            f"error={item.get('error')}",
        )
    if failed > 0:
        _ui().hint("Run `comfysql doctor <server>` and retry `comfysql copy-assets <server> --all`.")
    if failed > 0:
        return EXIT_RUNTIME
    return 0


def _sql_quote(text: str) -> str:
    return text.replace("'", "''")


def cmd_bind_character(args: argparse.Namespace) -> int:
    engine = _build_sql_engine(args)
    workflow = str(getattr(args, "workflow", "") or "").strip()
    character = str(getattr(args, "character", "") or "").strip()
    image_raw = str(getattr(args, "image", "") or "").strip()
    binding = str(getattr(args, "binding", "input_image") or "input_image").strip()
    do_upload = bool(getattr(args, "upload", False))
    timeout = float(getattr(args, "timeout", DEFAULT_SUBMIT_TIMEOUT))

    if not workflow or not character or not image_raw:
        raise CliError("bind-character requires --workflow, --character, and --image.", exit_code=2)

    _confirm_non_sql_mutation_if_needed(
        yes=bool(getattr(args, "yes", False)),
        prompt="This command updates character binding state.",
    )

    mapped_image = image_raw
    upload_report: dict[str, Any] | None = None
    if do_upload:
        prompt = {"1": {"class_type": "LoadImage", "inputs": {"image": image_raw}}}
        try:
            patched, upload_report = engine._auto_upload_local_assets(prompt, timeout=timeout)
        except SQLEngineError as exc:
            raise CliError(str(exc), exit_code=exc.exit_code) from exc
        mapped_value = patched.get("1", {}).get("inputs", {}).get("image")
        if isinstance(mapped_value, str) and mapped_value.strip():
            mapped_image = mapped_value.strip()

    try:
        spec = engine.upsert_character_binding(
            workflow_table=workflow,
            character_name=character,
            binding_key=binding,
            binding_value=mapped_image,
        )
        action = "upserted"
    except SQLEngineError as exc:
        raise CliError(str(exc), exit_code=exc.exit_code) from exc

    print(
        f"character_bound action={action} workflow={spec.workflow_table} character={spec.character_name} "
        f"binding={spec.binding_key} image={spec.binding_value}",
        flush=True,
    )
    if isinstance(upload_report, dict):
        print(
            f"upload_preflight uploaded={upload_report.get('uploaded_count', 0)} "
            f"skipped_existing={upload_report.get('skipped_existing_count', 0)} "
            f"failed={upload_report.get('failed_count', 0)}",
            flush=True,
        )
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
    _ui().section(f"sync server={args.host}:{args.port}")
    log("syncing nodes and models")
    report = _sync_schema_and_models(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        start_timeout=getattr(args, "start_timeout", DEFAULT_START_TIMEOUT),
        write_report=True,
    )

    _ui().success("sync completed")
    _ui().line(
        f"sync_done schema_tables={report['schema_tables']} "
        f"models={report['models_count']} "
        f"categories={len(report.get('categories', []))} "
        f"report={report.get('report_path', '')}",
    )
    return 0


def _resolve_download_url(raw_url: str, *, host: str, port: int) -> str:
    text = str(raw_url or "").strip()
    if not text:
        raise CliError("Provide --url for download.", exit_code=2)
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if text.startswith("/"):
        return _http_url(host, port, text)
    if text.startswith("view?"):
        return _http_url(host, port, f"/{text}")
    raise CliError("Download URL must be absolute (http/https) or start with /view? or view?.", exit_code=2)


def cmd_download(args: argparse.Namespace) -> int:
    _ui().section(f"download server={args.host}:{args.port}")
    url = _resolve_download_url(str(getattr(args, "url", "")), host=args.host, port=args.port)
    out_arg = str(getattr(args, "output", "") or "").strip()
    if out_arg:
        out_path = Path(out_arg).expanduser().resolve()
    else:
        parsed = parse.urlparse(url)
        q = parse.parse_qs(parsed.query)
        filename = ""
        values = q.get("filename")
        if isinstance(values, list) and values and isinstance(values[0], str):
            filename = values[0]
        out_path = (Path.cwd() / (filename or "download.bin")).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen_with_auth_fallback(url, method="GET", headers=_request_headers(), timeout=float(getattr(args, "timeout", 30.0))) as resp:
            raw = resp.read()
    except Exception as exc:
        raise CliError(f"download_failed url={url} error={exc}", exit_code=4) from exc
    out_path.write_bytes(raw)
    _ui().success(f"downloaded path={out_path} bytes={len(raw)}")
    return 0


def cmd_config_init(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve() if args.path else (_find_workspace_root() / DEFAULT_CONFIG_FILE)
    if path.exists() and not args.force:
        raise CliError(f"Config already exists: {path} (use --force to overwrite)", exit_code=2)
    payload = _build_default_config_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _ui().success(f"config_written path={path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    prog_name = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "comfy-agent"
    parser = argparse.ArgumentParser(prog=prog_name, description="Custom Comfy server CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    status_cmd = sub.add_parser("status", help="Show target server status")
    status_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    status_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    status_cmd.add_argument("--host", default=DEFAULT_HOST)
    status_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    status_cmd.add_argument("--output", choices=["text", "json"], default="text")
    status_cmd.set_defaults(func=cmd_status)

    doctor_cmd = sub.add_parser("doctor", help="Run remote server connection diagnostics")
    doctor_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    doctor_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    doctor_cmd.add_argument("--host", default=DEFAULT_HOST)
    doctor_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    doctor_cmd.add_argument("--timeout", type=float, default=5.0)
    doctor_cmd.add_argument("--full", action="store_true", help="Run extended preflight checks.")
    doctor_cmd.add_argument("--output", choices=["text", "json"], default="text")
    doctor_cmd.set_defaults(func=cmd_doctor)

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
    copy_assets_cmd.add_argument("--yes", action="store_true", help="Skip mutation confirmation prompts.")
    copy_assets_cmd.add_argument("--output", choices=["text", "json"], default="text")
    copy_assets_cmd.set_defaults(func=cmd_copy_assets)

    bind_character_cmd = sub.add_parser(
        "bind-character",
        help="Create or update a relational character binding (for example char_nick) for a workflow input.",
    )
    bind_character_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    bind_character_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    bind_character_cmd.add_argument("--host", default=DEFAULT_HOST)
    bind_character_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    bind_character_cmd.add_argument("--timeout", type=float, default=DEFAULT_SUBMIT_TIMEOUT)
    bind_character_cmd.add_argument("--workflow", required=True, help="Workflow table name (for example: img2img_controlnet).")
    bind_character_cmd.add_argument("--character", required=True, help="Character alias (for example: char_nick).")
    bind_character_cmd.add_argument("--image", required=True, help="Image filename/path (for example: nick.jpg.avif).")
    bind_character_cmd.add_argument(
        "--binding",
        default="input_image",
        help="Workflow bind key (default: input_image). For multi-input workflows you can use keys like 198.image.",
    )
    bind_character_cmd.add_argument(
        "--upload",
        action="store_true",
        help="Attempt to auto-upload local image before binding preset value.",
    )
    bind_character_cmd.add_argument("--yes", action="store_true", help="Skip mutation confirmation prompts.")
    bind_character_cmd.set_defaults(func=cmd_bind_character)

    sync_cmd = sub.add_parser("sync", help="Sync node schema and model inventory from server")
    sync_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    sync_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    sync_cmd.add_argument("--host", default=DEFAULT_HOST)
    sync_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    sync_cmd.add_argument("--start-timeout", type=float, default=DEFAULT_START_TIMEOUT)
    sync_cmd.add_argument("--timeout", type=float, default=DEFAULT_SUBMIT_TIMEOUT)
    sync_cmd.add_argument("--yes", action="store_true", help="Reserved for automation compatibility.")
    sync_cmd.set_defaults(func=cmd_sync)

    download_cmd = sub.add_parser("download", help="Download a file from Comfy endpoint URL (for example /view?...).")
    download_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    download_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    download_cmd.add_argument("--host", default=DEFAULT_HOST)
    download_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    download_cmd.add_argument("--url", required=True, help="Absolute URL, /view?... path, or view?... query path.")
    download_cmd.add_argument("--output", help="Local output file path (defaults to query filename or ./download.bin).")
    download_cmd.add_argument("--timeout", type=float, default=30.0)
    download_cmd.set_defaults(func=cmd_download)

    submit_cmd = sub.add_parser("submit", help="Submit workflow JSON")
    submit_cmd.add_argument(
        "server_or_workflow",
        help="Workflow path, or server alias when passing a second workflow argument.",
    )
    submit_cmd.add_argument("workflow", nargs="?", help="Path to API prompt workflow JSON")
    submit_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    submit_cmd.add_argument("--host", default=DEFAULT_HOST)
    submit_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    submit_cmd.add_argument("--timeout", type=float, default=DEFAULT_SUBMIT_TIMEOUT)
    submit_cmd.add_argument("--no-cache", action="store_true", help="Force a fresh run by randomizing seed inputs")
    submit_cmd.add_argument("--skip-validate", action="store_true", help="Skip preflight validate+sync before submit")
    submit_cmd.add_argument("--yes", action="store_true", help="Reserved for automation compatibility.")
    submit_cmd.set_defaults(func=cmd_submit, server="")

    validate_cmd = sub.add_parser("validate", help="Validate workflow JSON using local validator policies")
    validate_cmd.add_argument(
        "server_or_workflow",
        help="Workflow path, or server alias when passing a second workflow argument.",
    )
    validate_cmd.add_argument("workflow", nargs="?", help="Path to workflow JSON (API prompt or UI workflow)")
    validate_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    validate_cmd.add_argument("--host", default=DEFAULT_HOST)
    validate_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    validate_cmd.set_defaults(func=cmd_validate, server="")

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
    sql_cmd.add_argument("--output", choices=["text", "json"], default="text")
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

    sql_report_cmd = sub.add_parser("sql-report", help="Run one SQL statement and export a Markdown run report.")
    sql_report_cmd.add_argument("server", nargs="?", help="Server alias from config (for example: localhost, remote)")
    sql_report_cmd.add_argument("--config", help=f"Config file path (default: ./{DEFAULT_CONFIG_FILE})")
    sql_report_cmd.add_argument("--sql", help="Single ComfySQL statement text")
    sql_report_cmd.add_argument("--sql-file", help="Path to file containing exactly one SQL statement")
    sql_report_cmd.add_argument("--host", default=DEFAULT_HOST)
    sql_report_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    sql_report_cmd.add_argument("--timeout", type=float, default=DEFAULT_SUBMIT_TIMEOUT)
    sql_report_cmd.add_argument("--no-cache", action="store_true")
    sql_report_cmd.add_argument("--compile-only", action="store_true")
    sql_report_cmd.add_argument("--upload-mode", choices=["strict", "warn", "off"], default="strict")
    sql_report_cmd.add_argument("--download-output", dest="download_output", action="store_true", default=True)
    sql_report_cmd.add_argument("--no-download-output", dest="download_output", action="store_false")
    sql_report_cmd.add_argument("--download-dir", help="Local folder to save downloaded outputs (default: ./output).")
    sql_report_cmd.add_argument("--report", help="Output markdown path (default: ./reports/sql_run_<timestamp>.md)")
    sql_report_cmd.add_argument("--title", help="Optional markdown report title")
    sql_report_cmd.add_argument("--image", action="append", help="Extra image path(s) to embed in the report")
    sql_report_cmd.add_argument("--output", choices=["text", "json"], default="text")
    sql_report_cmd.set_defaults(func=cmd_sql_report)

    config_cmd = sub.add_parser("config", help="Manage comfysql config")
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)
    config_init = config_sub.add_parser("init", help="Write a starter config file")
    config_init.add_argument("--path", help=f"Output path (default: ./{DEFAULT_CONFIG_FILE})")
    config_init.add_argument("--force", action="store_true", help="Overwrite if file exists")
    config_init.add_argument("--yes", action="store_true", help="Reserved for automation compatibility.")
    config_init.set_defaults(func=cmd_config_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _set_output_mode(args)
    if getattr(args, "command", None) in {"submit", "validate"}:
        server_or_workflow = str(getattr(args, "server_or_workflow", "") or "").strip()
        workflow_arg = str(getattr(args, "workflow", "") or "").strip()
        if workflow_arg and server_or_workflow:
            args.server = server_or_workflow
    if getattr(args, "command", None) not in {"config", "pull"}:
        _apply_connection_settings(args)
    try:
        return int(args.func(args))
    except CliError as exc:
        message = str(exc)
        if _OUTPUT_FORMAT == "json":
            return _emit_json_error(message, original_exit_code=exc.exit_code)
        _print_error_with_hint(message, to_stderr=True)
        return _normalized_error_exit_code(message, original_code=exc.exit_code)
    except Exception as exc:
        message = f"Unexpected CLI error: {exc}"
        if _OUTPUT_FORMAT == "json":
            return _emit_json_error(message, original_exit_code=EXIT_RUNTIME)
        _print_error_with_hint(message, to_stderr=True)
        return EXIT_RUNTIME
    except KeyboardInterrupt:
        # Respect Ctrl-C for foreground command control.
        if signal.getsignal(signal.SIGINT) is not None:
            print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
