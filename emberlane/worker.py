"""Local Emberlane worker with explicit, allow-listed task handlers.

This is a local task runner, not a remote service or an OS sandbox. It never
runs arbitrary shell commands. The test handler invokes one fixed Python
unittest command against the configured repository root.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .mailbox import GitHubIssueMailbox
from .queue import Task, TaskQueue
from .workspace import Workspace, WorkspaceError

MAX_OUTPUT_CHARS = 20_000
GIT_COMMAND_TIMEOUT = 10
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
            "write_files": self._write_files,
            "replace_text": self._replace_text,
            "read_file": self._read_file,
            "list_files": self._list_files,
            "run_tests": self._run_tests,
            "git_status": self._git_status,
            "git_diff": self._git_diff,
            "diagnostics": self._diagnostics,
        }

    def _write_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = _checked_path(payload.get("path"))
        content = payload.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        self.workspace.write_text(path, content)
        return {"path": path, "bytes_written": len(content.encode("utf-8"))}

    def _write_files(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write a validated batch of files; each file replacement is atomic, the batch is not."""
        files = payload.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("files must be a non-empty list")
        if len(files) > 50:
            raise ValueError("a write_files task may contain at most 50 files")

        validated: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("each files entry must be an object")
            path = _checked_path(item.get("path"))
            content = item.get("content")
            if not isinstance(content, str):
                raise ValueError("each files entry must have string content")
            if path in seen:
                raise ValueError(f"duplicate path in files batch: {path}")
            if len(content.encode("utf-8")) > self.workspace.max_file_bytes:
                raise WorkspaceError(f"content exceeds configured size limit: {path}")
            seen.add(path)
            validated.append((path, content))

        # Preflight all targets without creating directories or changing files.
        # Workspace.write_text revalidates each target immediately before writing.
        for path, _content in validated:
            self.workspace.validate_write_path(path)

        written = []
        for path, content in validated:
            self.workspace.write_text(path, content)
            written.append({"path": path, "bytes_written": len(content.encode("utf-8"))})
        return {"files_written": written, "count": len(written), "batch_atomic": False}

    def _replace_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Replace an exact text fragment only when its expected count matches."""
        path = _checked_path(payload.get("path"))
        old = payload.get("old")
        new = payload.get("new")
        expected_count = payload.get("expected_count", 1)
        if not isinstance(old, str) or not old:
            raise ValueError("old must be a non-empty string")
        if not isinstance(new, str):
            raise ValueError("new must be a string")
        if (
            isinstance(expected_count, bool)
            or not isinstance(expected_count, int)
            or expected_count < 1
            or expected_count > 1000
        ):
            raise ValueError("expected_count must be an integer from 1 to 1000")

        current = self.workspace.read_text(path)
        actual_count = current.count(old)
        if actual_count != expected_count:
            raise ValueError(
                f"expected {expected_count} occurrence(s) of old text, found {actual_count}; file unchanged"
            )
        updated = current.replace(old, new)
        size = len(updated.encode("utf-8"))
        if size > self.workspace.max_file_bytes:
            raise WorkspaceError("updated content exceeds configured size limit")
        self.workspace.write_text(path, updated)
        return {
            "path": path,
            "replacements": expected_count,
            "bytes_written": size,
        }

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
        return {
            "command": "python -m unittest discover -s tests -v",
            "returncode": completed.returncode,
            "passed": completed.returncode == 0,
            "output": output,
        }

    def _run_git_readonly(self, args: list[str]) -> dict[str, Any]:
        command = ["git", *args]
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
                check=False,
                shell=False,
            )
            return {
                "command": command,
                "returncode": completed.returncode,
                "output": completed.stdout or "",
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "command": command,
                "returncode": None,
                "error": type(exc).__name__,
            }

    def _git_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {
            "status": self._run_git_readonly(["status", "--short", "--branch"]),
            "head": self._run_git_readonly(["log", "-1", "--oneline"]),
        }

    def _git_diff(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return diff metadata only; never publish source patches to the mailbox."""
        path = payload.get("path")
        suffix: list[str] = []
        if path is not None:
            suffix = [_checked_path(path)]
        names = self._run_git_readonly(["diff", "--name-only", "--", *suffix])
        stat = self._run_git_readonly(["diff", "--stat", "--", *suffix])
        staged_names = self._run_git_readonly(
            ["diff", "--cached", "--name-only", "--", *suffix]
        )
        staged_stat = self._run_git_readonly(
            ["diff", "--cached", "--stat", "--", *suffix]
        )
        return {
            "files": names,
            "stat": stat,
            "staged_files": staged_names,
            "staged_stat": staged_stat,
            "patch_included": False,
        }

    def _diagnostics(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {
            "root": str(self.root),
            "python_version": sys.version,
            "platform": platform.platform(),
            "git_status": self._run_git_readonly(["status", "--short", "--branch"]),
            "latest_commit": self._run_git_readonly(["log", "-1", "--oneline"]),
        }

    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> Task:
        if kind not in self.handlers:
            raise ValueError(f"unsupported task kind: {kind}")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        # Reject protected file targets before they enter the retry queue.
        if kind in {"write_file", "read_file"}:
            _checked_path(payload.get("path"))
        if kind == "replace_text":
            _checked_path(payload.get("path"))
            old = payload.get("old")
            new = payload.get("new")
            expected_count = payload.get("expected_count", 1)
            if not isinstance(old, str) or not old:
                raise ValueError("old must be a non-empty string")
            if not isinstance(new, str):
                raise ValueError("new must be a string")
            if len(new.encode("utf-8")) > self.workspace.max_file_bytes:
                raise WorkspaceError("replacement text exceeds configured size limit")
            if (
                isinstance(expected_count, bool)
                or not isinstance(expected_count, int)
                or expected_count < 1
                or expected_count > 1000
            ):
                raise ValueError("expected_count must be an integer from 1 to 1000")
        if kind == "write_files":
            files = payload.get("files")
            if not isinstance(files, list) or not files:
                raise ValueError("files must be a non-empty list")
            if len(files) > 50:
                raise ValueError("a write_files task may contain at most 50 files")
            seen: set[str] = set()
            for item in files:
                if not isinstance(item, dict):
                    raise ValueError("each files entry must be an object")
                path = _checked_path(item.get("path"))
                if path in seen:
                    raise ValueError(f"duplicate path in files batch: {path}")
                content = item.get("content")
                if not isinstance(content, str):
                    raise ValueError("each files entry must have string content")
                if len(content.encode("utf-8")) > self.workspace.max_file_bytes:
                    raise WorkspaceError(f"content exceeds configured size limit: {path}")
                seen.add(path)
        if kind == "git_diff" and payload.get("path") is not None:
            _checked_path(payload.get("path"))
        return self.queue.submit(kind, payload, idempotency_key=idempotency_key)

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
    submit_parser.add_argument("kind", choices=("write_file", "write_files", "replace_text", "read_file", "list_files", "run_tests", "git_status", "git_diff", "diagnostics"))
    submit_parser.add_argument("--payload", default="{}", help="task payload as JSON object")

    sub.add_parser("run-one", help="execute at most one pending task")
    mailbox_parser = sub.add_parser(
        "mailbox-once", help="poll one GitHub issue for one authorized task"
    )
    mailbox_parser.add_argument("--repo", required=True, help="GitHub owner/repository")
    mailbox_parser.add_argument("--issue", required=True, type=int, help="mailbox issue number")
    mailbox_parser.add_argument("--author", required=True, help="only accept tasks from this GitHub login")
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

    if args.command == "mailbox-once":
        mailbox = GitHubIssueMailbox(
            worker, args.repo, args.issue, args.author
        )
        print(json.dumps(mailbox.run_once(), ensure_ascii=False, indent=2))
        return 0

    tasks = worker.queue.list_tasks()
    print(json.dumps([{
        "task_id": t.task_id, "kind": t.kind, "status": t.status,
        "attempts": t.attempts, "last_error": t.last_error, "result": t.result,
    } for t in tasks], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
