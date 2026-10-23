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

from .local_model import LocalModelConfig, LocalModelError, LocalModelRunner
from .mailbox import GitHubIssueMailbox
from .planner import GoalPlanner
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
            "git_stash_inspect": self._git_stash_inspect,
            "git_diff": self._git_diff,
            "git_sync": self._git_sync,
            "diagnostics": self._diagnostics,
            "plan_goal": self._plan_goal,
            "local_model": self._local_model,
        }

    def _local_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate text locally; model errors are explicit terminal task failures."""
        try:
            config = LocalModelConfig.from_env()
            return LocalModelRunner(config).generate(payload["prompt"])
        except LocalModelError as exc:
            return {
                "ok": False,
                "error_code": exc.code,
                "error": str(exc),
                "returncode": exc.returncode,
            }

    def _plan_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Advance a bounded plan using only the worker's registered handlers."""
        planner = GoalPlanner(self.queue, set(self.handlers) - {"plan_goal"})
        return planner.advance(payload)

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
        if not payload.get("include_content", False):
            return {"path": path, "content": content}
        if len(content) > MAX_OUTPUT_CHARS:
            return {
                "path": path,
                "content_included": False,
                "content_chars": len(content),
                "content_omitted_reason": f"source exceeds {MAX_OUTPUT_CHARS}-character opt-in preview limit",
            }
        return {
            "path": path,
            "content_included": True,
            "content_chars": len(content),
            "source_text": content,
        }

    def _list_files(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {"files": self.workspace.list_files()}

    def _run_tests(self, payload: dict[str, Any]) -> dict[str, Any]:
        test_file = payload.get("test_file")
        if test_file is not None:
            target = self.root / "tests" / test_file
            if not target.is_file():
                return {
                    "command": None,
                    "returncode": 2,
                    "passed": False,
                    "error": "test_file_not_found",
                    "output": f"Test file not found: tests/{test_file}",
                }
            command = [
                sys.executable, "-m", "unittest", "discover",
                "-s", "tests", "-p", test_file, "-v",
            ]
            command_label = f"python -m unittest discover -s tests -p {test_file} -v"
        else:
            command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
            command_label = "python -m unittest discover -s tests -v"
        completed = subprocess.run(
            command,
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
            "command": command_label,
            "returncode": completed.returncode,
            "passed": completed.returncode == 0,
            "output": output,
        }

    def _run_git_readonly(
        self, args: list[str], *, timeout: int = GIT_COMMAND_TIMEOUT
    ) -> dict[str, Any]:
        command = ["git", *args]
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
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
        untracked = self._run_git_readonly(
            ["ls-files", "--others", "--exclude-standard", "--", *suffix]
        )
        return {
            "files": names,
            "stat": stat,
            "staged_files": staged_names,
            "staged_stat": staged_stat,
            "untracked_files": untracked,
            "patch_included": False,
        }

    def _git_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Fast-forward the current branch from origin only when the worktree is clean."""
        expected_branch = payload.get("expected_branch")
        if expected_branch is not None and (
            not isinstance(expected_branch, str)
            or not expected_branch
            or expected_branch.startswith("-")
            or any(ch.isspace() for ch in expected_branch)
        ):
            raise ValueError("expected_branch must be a valid branch name")

        allow_matching_worktree = payload.get("allow_matching_worktree", False)
        if not isinstance(allow_matching_worktree, bool):
            raise ValueError("allow_matching_worktree must be a boolean")

        status = self._run_git_readonly(["status", "--porcelain"])
        if status["returncode"] != 0:
            return {"synced": False, "stage": "preflight_status", "status": status}
        initial_status = status["output"]
        if initial_status.strip() and not allow_matching_worktree:
            return {
                "synced": False,
                "stage": "preflight_dirty",
                "error": "working tree is not clean; no fetch or merge was attempted",
                "status": status,
            }

        branch = self._run_git_readonly(["branch", "--show-current"])
        if branch["returncode"] != 0 or not branch["output"].strip():
            return {"synced": False, "stage": "current_branch", "branch": branch}
        current_branch = branch["output"].strip()
        if current_branch.startswith("-") or any(ch.isspace() for ch in current_branch):
            return {
                "synced": False,
                "stage": "current_branch",
                "error": "current branch name failed validation",
                "branch": branch,
            }
        if expected_branch is not None and current_branch != expected_branch:
            return {
                "synced": False,
                "stage": "branch_mismatch",
                "expected_branch": expected_branch,
                "current_branch": current_branch,
            }

        fetch = self._run_git_readonly(["fetch", "origin", current_branch], timeout=60)
        if fetch["returncode"] != 0:
            return {
                "synced": False,
                "stage": "fetch",
                "branch": current_branch,
                "fetch": fetch,
            }

        if initial_status.strip():
            # Bootstrap only if the sole local changes are unstaged tracked edits
            # whose worktree bytes already match the fetched commit exactly.
            staged = self._run_git_readonly(["diff", "--cached", "--quiet"])
            untracked = self._run_git_readonly(
                ["ls-files", "--others", "--exclude-standard"]
            )
            changed = self._run_git_readonly(["diff", "--name-only"])
            if (
                staged["returncode"] != 0
                or untracked["returncode"] != 0
                or changed["returncode"] != 0
                or untracked["output"].strip()
                or not changed["output"].strip()
            ):
                return {
                    "synced": False,
                    "stage": "matching_worktree_preflight",
                    "error": "bootstrap requires only unstaged tracked modifications and no untracked files",
                    "status": status,
                    "staged": staged,
                    "untracked": untracked,
                    "changed": changed,
                }
            for changed_path in changed["output"].splitlines():
                compare = self._run_git_readonly(
                    ["diff", "--quiet", "FETCH_HEAD", "--", changed_path]
                )
                if compare["returncode"] != 0:
                    return {
                        "synced": False,
                        "stage": "matching_worktree_mismatch",
                        "path": changed_path,
                        "comparison": compare,
                    }
            stash = self._run_git_readonly(
                ["stash", "push", "-m", "emberlane-bootstrap-sync"], timeout=30
            )
            if stash["returncode"] != 0:
                return {
                    "synced": False,
                    "stage": "bootstrap_stash",
                    "stash": stash,
                }
            # Keep the verified duplicate in the stash as a recovery record.
            # The fetched commit already contains the exact same file bytes.
            sync = self._run_git_readonly(
                ["merge", "--ff-only", "FETCH_HEAD"], timeout=30
            )
            if sync["returncode"] != 0:
                return {
                    "synced": False,
                    "stage": "bootstrap_fast_forward",
                    "stash": stash,
                    "sync": sync,
                }
        else:
            stash = None
            sync = self._run_git_readonly(
                ["merge", "--ff-only", "FETCH_HEAD"], timeout=30
            )
        if sync["returncode"] != 0:
            return {
                "synced": False,
                "stage": "fast_forward" if not initial_status.strip() else "bootstrap_fast_forward",
                "branch": current_branch,
                "fetch": fetch,
                "stash": stash,
                "sync": sync,
            }
        final_status = self._run_git_readonly(["status", "--short", "--branch"])
        clean_status = self._run_git_readonly(["status", "--porcelain"])
        head = self._run_git_readonly(["log", "-1", "--oneline"])
        head_sha = self._run_git_readonly(["rev-parse", "HEAD"])
        target_sha = self._run_git_readonly(["rev-parse", "FETCH_HEAD"])
        common = {
            "branch": current_branch,
            "fetch": fetch,
            "sync": sync,
            "stash": stash,
            "bootstrap_matching_worktree": bool(initial_status.strip()),
            "status": final_status,
            "clean_status": clean_status,
            "head": head,
            "head_sha": head_sha,
            "target_sha": target_sha,
        }
        if final_status["returncode"] != 0 or clean_status["returncode"] != 0:
            return {"synced": False, "stage": "postflight_status", **common}
        if clean_status["output"].strip():
            return {"synced": False, "stage": "postflight_dirty", **common}
        if head["returncode"] != 0 or head_sha["returncode"] != 0 or target_sha["returncode"] != 0:
            return {"synced": False, "stage": "postflight_head", **common}
        if head_sha["output"].strip() != target_sha["output"].strip():
            return {"synced": False, "stage": "postflight_head_mismatch", **common}
        return {"synced": True, "stage": "complete", **common}

    def _git_stash_inspect(self, payload: dict[str, Any]) -> dict[str, Any]:
        """List recent stashes and inspect their file summaries without applying them."""
        del payload
        listing = self._run_git_readonly(["stash", "list", "--format=%gd %gs"])
        if listing["returncode"] != 0:
            return {"listing": listing, "entries": [], "max_entries": 10}

        entries = []
        for line in listing["output"].splitlines()[:10]:
            ref = line.split(" ", 1)[0]
            if not (
                ref.startswith("stash@{")
                and ref.endswith("}")
                and ref[7:-1].isdigit()
            ):
                continue
            stat = self._run_git_readonly(
                ["stash", "show", "--stat", "--include-untracked", ref]
            )
            entries.append({"ref": ref, "summary": line, "stat": stat})
        return {"listing": listing, "entries": entries, "max_entries": 10}

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
        if kind == "read_file" and not isinstance(payload.get("include_content", False), bool):
            raise ValueError("include_content must be a boolean")
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
        if kind == "local_model":
            prompt = payload.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("local_model requires a non-empty prompt")
            if len(prompt) > 16_000:
                raise ValueError("local_model prompt exceeds 16000 characters")
            unexpected = set(payload) - {"prompt"}
            if unexpected:
                raise ValueError(f"unsupported local_model payload keys: {sorted(unexpected)}")
        if kind == "run_tests":
            test_file = payload.get("test_file")
            if test_file is not None and (
                not isinstance(test_file, str)
                or not test_file.startswith("test_")
                or not test_file.endswith(".py")
                or Path(test_file).name != test_file
                or any(ch.isspace() for ch in test_file)
                or any(ch in test_file for ch in "*?[]:")
            ):
                raise ValueError("test_file must be a test_*.py filename directly inside tests/")
        if kind == "git_diff" and payload.get("path") is not None:
            _checked_path(payload.get("path"))
        if kind == "git_sync":
            expected_branch = payload.get("expected_branch")
            if expected_branch is not None and (
                not isinstance(expected_branch, str)
                or not expected_branch
                or expected_branch.startswith("-")
                or any(ch.isspace() for ch in expected_branch)
            ):
                raise ValueError("expected_branch must be a valid branch name")
        return self.queue.submit(kind, payload, idempotency_key=idempotency_key)

    def run_one(self) -> Task | None:
        return self.queue.run_one(self.handlers)

    def resume_deferred(self, task_id: str) -> Task:
        """Resume a deferred task and continue its waiting goal plan, if any."""
        task = self.queue.resume_deferred(task_id)
        key = task.idempotency_key or ""
        if not key.startswith("goal:") or ":step:" not in key:
            return task
        goal_id = key[len("goal:"):].split(":step:", 1)[0]
        waiting_plans = [
            candidate for candidate in self.queue.list_tasks()
            if candidate.kind == "plan_goal"
            and candidate.status == "completed"
            and isinstance(candidate.result, dict)
            and candidate.result.get("goal_id") == goal_id
            and candidate.result.get("status") == "waiting"
            and isinstance(candidate.payload, dict)
        ]
        if not waiting_plans:
            return task
        previous = max(waiting_plans, key=lambda item: item.payload.get("cycle", 0))
        cycle = previous.payload.get("cycle", 0) + 1
        max_cycles = previous.payload.get("max_cycles", 20)
        if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle > max_cycles:
            return task
        self.queue.submit(
            "plan_goal",
            {**previous.payload, "cycle": cycle},
            idempotency_key=f"goal:{goal_id}:planner:cycle:{cycle}",
        )
        return task


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
    submit_parser.add_argument("kind", choices=("write_file", "write_files", "replace_text", "read_file", "list_files", "run_tests", "git_status", "git_diff", "git_sync", "git_stash_inspect", "diagnostics", "local_model"))
    submit_parser.add_argument("--payload", default="{}", help="task payload as JSON object")

    sub.add_parser("run-one", help="execute at most one pending task")
    resume_parser = sub.add_parser(
        "resume-deferred", help="resume a deferred task after its external wait clears"
    )
    resume_parser.add_argument("task_id", help="task identifier reported by status")
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

    if args.command == "resume-deferred":
        try:
            task = worker.resume_deferred(args.task_id)
        except (KeyError, ValueError) as exc:
            parser.error(str(exc))
        _print_task(task)
        return 0

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
