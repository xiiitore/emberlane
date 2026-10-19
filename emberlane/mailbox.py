"""GitHub issue-comment mailbox for a local Emberlane worker.

Tasks are JSON comments from one explicitly configured GitHub account.
Only registered task kinds are accepted; no arbitrary shell commands are run.
Requires the GitHub CLI (gh) to be installed and authenticated locally.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

TASK_MARKER = "EMBERLANE_TASK_JSON"
MAX_COMMENT_CHARS = 20_000


class MailboxError(RuntimeError):
    pass


def _gh(args: list[str], *, input_text: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MailboxError(f"GitHub CLI failed: {exc}") from exc
    if result.returncode:
        message = result.stderr.strip() or f"gh exited {result.returncode}"
        raise MailboxError(message[:2000])
    return result.stdout


def _task_from_comment(body: str) -> dict[str, Any] | None:
    lines = body.splitlines()
    if not lines or lines[0].strip() != TASK_MARKER:
        return None
    try:
        task = json.loads("\n".join(lines[1:]))
    except json.JSONDecodeError as exc:
        raise MailboxError(f"invalid task JSON: {exc}") from exc
    if not isinstance(task, dict) or set(task) != {"kind", "payload"}:
        raise MailboxError("task must contain exactly 'kind' and 'payload'")
    if not isinstance(task["kind"], str) or not isinstance(task["payload"], dict):
        raise MailboxError("task kind must be a string and payload must be an object")
    return task


class GitHubIssueMailbox:
    """Poll one issue; accept tasks only from the configured GitHub login."""

    def __init__(
        self,
        worker: Any,
        repository: str,
        issue_number: int,
        author: str,
        state_path: str | Path | None = None,
    ):
        if "/" not in repository or issue_number < 1 or not author:
            raise ValueError("repository, positive issue number, and author are required")
        self.worker = worker
        self.repository = repository
        self.issue_number = issue_number
        self.author = author.casefold()
        self.state_path = Path(state_path or worker.root / ".emberlane" / "mailbox-state.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"handled": [], "active": {}}
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("handled"), list) or not isinstance(value.get("active"), dict):
            raise MailboxError("mailbox state has invalid structure")
        return value

    def _save_state(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def _comments(self) -> list[dict[str, Any]]:
        endpoint = f"repos/{self.repository}/issues/{self.issue_number}/comments"
        raw = _gh(["api", endpoint, "--paginate"])
        value = json.loads(raw)
        if not isinstance(value, list):
            raise MailboxError("GitHub returned an unexpected comments response")
        return value

    def _reply(self, body: str) -> None:
        endpoint = f"repos/{self.repository}/issues/{self.issue_number}/comments"
        _gh(["api", "--method", "POST", endpoint, "-f", f"body={body[:MAX_COMMENT_CHARS]}"])

    def _finish_if_terminal(self, comment_id: str, task_id: str) -> bool:
        task = self.worker.queue.get(task_id)
        if task is None:
            self._reply(f"EMBERLANE_RESULT {comment_id}\nERROR: linked local task was not found.")
            self.state["handled"].append(comment_id)
            self.state["active"].pop(comment_id, None)
            self._save_state()
            return True
        if task.status not in {"completed", "failed"}:
            return False
        result = {
            "source_comment_id": comment_id,
            "task_id": task.task_id,
            "kind": task.kind,
            "status": task.status,
            "attempts": task.attempts,
            "last_error": task.last_error,
            "result": task.result,
        }
        self._reply("EMBERLANE_RESULT\n" + json.dumps(result, ensure_ascii=False, indent=2)[:MAX_COMMENT_CHARS])
        self.state["handled"].append(comment_id)
        self.state["active"].pop(comment_id, None)
        self._save_state()
        return True

    def run_once(self) -> dict[str, Any]:
        comments = self._comments()
        # Resume an already enqueued task first; never enqueue it twice after a restart.
        for comment_id, task_id in list(self.state["active"].items()):
            task = self.worker.queue.get(task_id)
            if task is not None and task.status == "pending":
                self.worker.run_one()
            if self._finish_if_terminal(comment_id, task_id):
                return {"status": "finished", "comment_id": comment_id, "task_id": task_id}

        handled = set(self.state["handled"])
        active = set(self.state["active"])
        for comment in comments:
            comment_id = str(comment.get("id", ""))
            if not comment_id or comment_id in handled or comment_id in active:
                continue
            user = comment.get("user") or {}
            if str(user.get("login", "")).casefold() != self.author:
                continue
            body = comment.get("body") or ""
            try:
                task_data = _task_from_comment(body)
            except MailboxError as exc:
                self._reply(f"EMBERLANE_RESULT {comment_id}\nREJECTED: {exc}")
                self.state["handled"].append(comment_id)
                self._save_state()
                return {"status": "rejected", "comment_id": comment_id, "error": str(exc)}
            if task_data is None:
                continue
            task = self.worker.submit(task_data["kind"], task_data["payload"])
            self.state["active"][comment_id] = task.task_id
            self._save_state()
            self.worker.run_one()
            if self._finish_if_terminal(comment_id, task.task_id):
                return {"status": "finished", "comment_id": comment_id, "task_id": task.task_id}
            return {"status": "pending", "comment_id": comment_id, "task_id": task.task_id}
        return {"status": "idle"}
