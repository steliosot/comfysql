from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.json import JSON
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn
from rich.table import Table


@dataclass
class SubmitProgressState:
    progress: Progress | None = None
    task_id: int | None = None
    last_line: str | None = None


class TerminalUI:
    def __init__(self) -> None:
        self.console = Console()
        # Auto policy: rich styles only when running in a real interactive terminal.
        self.styled = bool(self.console.is_terminal)

    def line(self, text: str) -> None:
        if self.styled:
            self.console.print(text)
        else:
            print(text, flush=True)

    def print_json(self, payload: dict[str, Any]) -> None:
        if self.styled:
            self.console.print(JSON.from_data(payload))
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=True), flush=True)

    def print_table(self, title: str, headers: list[str], rows: list[list[str]]) -> None:
        if not self.styled:
            print(title, flush=True)
            if not rows:
                print("- (none)", flush=True)
                return
            for row in rows:
                print("- " + " | ".join(row), flush=True)
            return

        table = Table(title=title, title_style="bold cyan", header_style="bold magenta")
        for header in headers:
            table.add_column(header)
        for row in rows:
            table.add_row(*row)
        self.console.print(table)

    def submit_begin(self) -> SubmitProgressState:
        state = SubmitProgressState()
        if not self.styled:
            print("submitted", flush=True)
            return state

        self.console.print("[bold cyan]submitted[/]")
        progress = Progress(
            TextColumn("[bold blue]{task.fields[label]}"),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            console=self.console,
            transient=False,
        )
        progress.start()
        task_id = progress.add_task("submit", total=100, completed=0, label="running")
        state.progress = progress
        state.task_id = task_id
        return state

    def submit_update(self, state: SubmitProgressState, line_text: str, pct: int) -> None:
        if not self.styled:
            if line_text != state.last_line:
                print(line_text, flush=True)
                state.last_line = line_text
            return
        if state.progress is None or state.task_id is None:
            return
        state.progress.update(state.task_id, completed=max(0, min(100, pct)), label="running")

    def submit_done(self, state: SubmitProgressState) -> None:
        if self.styled and state.progress is not None and state.task_id is not None:
            state.progress.update(state.task_id, completed=100, label="done")
            state.progress.stop()
            self.console.print("[bold green]executed[/]")
            return
        print("executed", flush=True)

    def submit_fail(self, state: SubmitProgressState, message: str) -> None:
        if self.styled and state.progress is not None:
            try:
                state.progress.stop()
            except Exception:
                pass
            self.console.print(f"[bold red]{message}[/]")

