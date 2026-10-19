"""Local Emberlane worker with explicit, allow-listed task handlers.

This is a local task runner, not a remote service or an OS sandbox. It never
runs arbitrary shell commands. The test handler invokes one fixed Python
unittest command against the configured repository root.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .queue import Task, TaskQueue
from .workspace import Workspace, WorkspaceError

MAX_OUTPUT_CHARS = 20_000
PROTECTED_PARTS = {".git", ".venv", ".emberlane", "__pycache__"}
PROTECTED_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}


def _checked_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise WorkspaceError("path must be a non-empty string")
    parts = Path(value).parts
    if any(part in PROTECTED_PARTS or part in PROTECTED_NAMES for part in parts):
        raise WorkspaceError("worker policy blocks protected paths")
    return value


class LocalWorker:
    """Runs registered tasks inside one configured project directory."""

    def __init__(
        self,
        root: str | Path = ".",
        state_path: str | Path | None = None,
        *,
        max_file_bytes: int = 1_000_000,
        test_timeout: int = 120,
    ):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("project root must be an existing directory")
        self.workspace = Workspace(self.root, max_file_bytes=max_file_bytes)
        self.queue = TaskQueue(
            state_path or self.root / ".emberlane" / "queue.json"
        )
        self.test_timeout = test_timeout
        self.handlers = {
            "write_file": self._write_file,
            "read_file": self._read_file,
            "list_files": self._list_files,
            "run_tests": self._run_tests,
        }

    def _write_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = _checked_path(payload.get("path"))
        content = payload.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        self.workspace.write_text(path, content)
        return {"path": path, "bytes_written": len(content.encode("utf-8"))}

    def _read_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = _checked_path(payload.get("path"))
        content = self.workspace.read_text(path)
        return {"path": path, "content": content}

    def _list_files(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {"files": self.workspace.list_files()}

    def _run_tests(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=self.test_timeout,
            check=False,
            shell=False,
        )
        output = completed.stdout or ""
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[-MAX_OUTPUT_CHARS:] + "\n[output truncated]"
        return {
            "command": "python -m unittest discover -s tests -v",
            "returncode": completed.returncode,
            "passed": completed.returncode == 0,
            "output": output,
        }

    def submit(self, kind: str, payload: dict[str, Any]) -> Task:
        if kind not in self.handlers:
            raise ValueError(f"unsupported task kind: {kind}")
        return self.queue.submit(kind, payload)

    def run_one(self) -> Task | None:
        return self.queue.run_one(self.handlers)


def _print_task(task: Task | None) -> None:
    if task is None:
        print("QUEUE_EMPTY")
        return
    print(json.dumps({
        "task_id": task.task_id,
        "kind": task.kind,
        "status": task.status,
        "attempts": task.attempts,
        "last_error": task.last_error,
        "result": task.result,
    }, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="emberlane", description="Local Emberlane worker")
    parser.add_argument("--root", default=".", help="project root (default: current directory)")
    parser.add_argument("--state", default=None, help="queue JSON path (default: ROOT/.emberlane/queue.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    submit_parser = sub.add_parser("submit", help="enqueue one allow-listed task")
    submit_parser.add_argument("kind", choices=("write_file", "read_file", "list_files", "run_tests"))
    submit_parser.add_argument("--payload", default="{}", help="task payload as JSON object")

    sub.add_parser("run-one", help="execute at most one pending task")
    sub.add_parser("status", help="show queued tasks")

    args = parser.parse_args(argv)
    worker = LocalWorker(args.root, args.state)

    if args.command == "submit":
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            parser.error(f"invalid JSON payload: {exc}")
        if not isinstance(payload, dict):
            parser.error("payload must be a JSON object")
        task = worker.submit(args.kind, payload)
        _print_task(task)
        return 0

    if args.command == "run-one":
        task = worker.run_one()
        _print_task(task)
        return 1 if task is not None and task.status == "failed" else 0

    tasks = worker.queue.list_tasks()
    print(json.dumps([{
        "task_id": t.task_id, "kind": t.kind, "status": t.status,
        "attempts": t.attempts, "last_error": t.last_error, "result": t.result,
    } for t in tasks], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
