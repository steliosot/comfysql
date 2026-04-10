from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path

from aiohttp import web

from comfy_custom import cli


class MockComfyServer:
    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.port: int | None = None
        self.submitted_payload: dict | None = None
        self._ws_clients: list[web.WebSocketResponse] = []

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws_clients.append(ws)
        try:
            async for _msg in ws:
                pass
        finally:
            if ws in self._ws_clients:
                self._ws_clients.remove(ws)
        return ws

    async def _get_prompt(self, _request: web.Request) -> web.Response:
        return web.json_response({"exec_info": {"queue_remaining": 0}})

    async def _post_prompt(self, request: web.Request) -> web.Response:
        self.submitted_payload = await request.json()
        prompt_id = self.submitted_payload.get("prompt_id", "")

        for ws in list(self._ws_clients):
            await ws.send_json({"type": "progress", "data": {"value": 1, "max": 2, "prompt_id": prompt_id, "node": "1"}})
            await ws.send_json({"type": "executing", "data": {"prompt_id": prompt_id, "node": None}})

        return web.json_response({"prompt_id": prompt_id, "number": 1, "node_errors": {}})

    def start(self) -> None:
        ready_queue: queue.Queue[int] = queue.Queue(maxsize=1)

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.loop = loop

            async def _setup() -> None:
                app = web.Application()
                app.router.add_get("/prompt", self._get_prompt)
                app.router.add_post("/prompt", self._post_prompt)
                app.router.add_get("/ws", self._ws_handler)
                self.runner = web.AppRunner(app)
                await self.runner.setup()
                self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
                await self.site.start()
                assert self.site._server is not None
                sockets = self.site._server.sockets
                assert sockets
                self.port = sockets[0].getsockname()[1]
                ready_queue.put(self.port)

            loop.run_until_complete(_setup())
            loop.run_forever()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()
        self.port = ready_queue.get(timeout=10)

    def stop(self) -> None:
        if self.loop is None:
            return

        async def _shutdown() -> None:
            if self.runner is not None:
                await self.runner.cleanup()

        fut = asyncio.run_coroutine_threadsafe(_shutdown(), self.loop)
        fut.result(timeout=10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=10)


def test_submit_workflow_integration(tmp_path: Path, monkeypatch, capsys) -> None:
    workflow = {
        "1": {
            "class_type": "TestNode",
            "inputs": {},
        }
    }
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

    server = MockComfyServer()
    server.start()
    assert server.port is not None

    monkeypatch.setattr(
        cli,
        "ensure_server_running",
        lambda host, port, timeout=cli.DEFAULT_START_TIMEOUT: cli.RuntimeState(
            pid=-1, host=host, port=port, log_path="", started_at=0.0
        ),
    )

    try:
        cli.submit_workflow(workflow_path=workflow_path, host="127.0.0.1", port=server.port, timeout=5)
    finally:
        server.stop()

    out = capsys.readouterr().out
    assert "submitted" in out
    assert "50%" in out
    assert "executed" in out
    assert server.submitted_payload is not None
    assert "prompt" in server.submitted_payload
    assert "client_id" in server.submitted_payload
    assert "prompt_id" in server.submitted_payload


def test_submit_auto_start_path_calls_ensure(tmp_path: Path, monkeypatch) -> None:
    workflow = {"1": {"class_type": "Node", "inputs": {}}}
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

    called = {"ensure": 0}

    def _ensure(host, port, timeout=cli.DEFAULT_START_TIMEOUT):
        called["ensure"] += 1
        return cli.RuntimeState(pid=1, host=host, port=port, log_path="", started_at=0.0)

    class DummyWS:
        def connect(self, *_args, **_kwargs):
            return None

        def settimeout(self, _value):
            return None

        def recv(self):
            return json.dumps({"type": "executing", "data": {"prompt_id": "p", "node": None}})

        def close(self):
            return None

    monkeypatch.setattr(cli, "ensure_server_running", _ensure)
    monkeypatch.setattr(cli.websocket, "WebSocket", DummyWS)
    monkeypatch.setattr(cli, "post_prompt", lambda **_kwargs: {"prompt_id": "p"})

    cli.submit_workflow(workflow_path=workflow_path, host="127.0.0.1", port=8188, timeout=2)

    assert called["ensure"] == 1
