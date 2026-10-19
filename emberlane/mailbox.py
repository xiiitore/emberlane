"""GitHub issue-comment mailbox for a local Emberlane worker.

Tasks are JSON comments from one explicitly configured GitHub account.
Only registered task kinds are accepted; no arbitrary shell commands are run.
Requires the GitHub CLI (gh) to be installed and authenticated locally.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

TASK_MARKER = "EMBERLANE_TASK_JSON"
MAX_COMMENT_CHARS = 20_000
MAX_GH_ATTEMPTS = 4
BASE_RETRY_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 30.0

_RETRYABLE_ERRORS = (
    "rate limit",
    "secondary rate limit",
    "abuse detection",
    "http 429",
    "http 502",
    "http 503",
    "http 504",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "connection reset",
    "connection refused",
    "temporary failure",
    "timed out",
)


class MailboxError(RuntimeError):
    pass


def _retry_after_seconds(message: str) -> float | None:
    """Return a bounded Retry-After delay if a CLI error exposes that header."""
    match = re.search(r"(?im)^\s*retry-after\s*:\s*(\d+(?:\.\d+)?)\s*$", message)
    if not match:
        return None
    try:
        seconds = float(match.group(1))
    except ValueError:
        return None
    return min(MAX_RETRY_DELAY_SECONDS, max(0.0, seconds))


def _is_retryable_error(message: str) -> bool:
    lowered = message.casefold()
    # A generic 403 can indicate missing permissions; retry only when GitHub
    # explicitly identifies a rate limit.
    return any(marker in lowered for marker in _RETRYABLE_ERRORS)


def _gh(args: list[str], *, input_text: str | None = None) -> str:
    """Run gh with bounded retries for transient API/network failures only."""
    for attempt in range(MAX_GH_ATTEMPTS):
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
        except subprocess.TimeoutExpired as exc:
            message = f"GitHub CLI timed out: {exc}"
            if attempt + 1 >= MAX_GH_ATTEMPTS:
                raise MailboxError(message[:2000]) from exc
            time.sleep(min(BASE_RETRY_DELAY_SECONDS * (2 ** attempt), MAX_RETRY_DELAY_SECONDS))
            continue
        except OSError as exc:
            # Missing executable and local process errors will not improve by retrying.
            raise MailboxError(f"GitHub CLI failed: {exc}") from exc

        if result.returncode == 0:
            return result.stdout

        message = result.stderr.strip() or result.stdout.strip() or f"gh exited {result.returncode}"
        if attempt + 1 >= MAX_GH_ATTEMPTS or not _is_retryable_error(message):
            raise MailboxError(message[:2000])

        retry_after = _retry_after_seconds(message)
        delay = retry_after if retry_after is not None else min(
            BASE_RETRY_DELAY_SECONDS * (2 ** attempt),
            MAX_RETRY_DELAY_SECONDS,
        )
        time.sleep(delay)

    raise MailboxError("GitHub CLI failed after bounded retries")


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
        raw = _gh(["api", endpoint, "--paginate", "--slurp"])
        pages = json.loads(raw)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise MailboxError("GitHub returned an unexpected comments response")
        return [comment for page in pages for comment in page]

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
        safe_result = task.result
        if isinstance(safe_result, dict):
            # The mailbox issue may be public: never echo file contents or raw
            # test output into GitHub comments.
            # Keep test-runner output visible for debugging. File contents remain
            # excluded from issue comments because the mailbox issue can be public.
            # Other task output remains structured-only unless explicitly reviewed.
            safe_result = {
                key: value for key, value in safe_result.items()
                if key != "content" and (key != "output" or task.kind == "run_tests")
            }
            if task.kind == "read_file":
                safe_result["content_returned_to_mailbox"] = False
        result = {
            "source_comment_id": comment_id,
            "task_id": task.task_id,
            "kind": task.kind,
            "status": task.status,
            "attempts": task.attempts,
            "last_error": task.last_error,
            "result": safe_result,
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
            try:
                task = self.worker.submit(
                    task_data["kind"], task_data["payload"],
                    idempotency_key=comment_id,
                )
            except Exception as exc:
                self._reply(f"EMBERLANE_RESULT {comment_id}\nREJECTED: {type(exc).__name__}: {exc}")
                self.state["handled"].append(comment_id)
                self._save_state()
                return {"status": "rejected", "comment_id": comment_id, "error": str(exc)}
            self.state["active"][comment_id] = task.task_id
            self._save_state()
            self.worker.run_one()
            if self._finish_if_terminal(comment_id, task.task_id):
                return {"status": "finished", "comment_id": comment_id, "task_id": task.task_id}
            return {"status": "pending", "comment_id": comment_id, "task_id": task.task_id}
        return {"status": "idle"}
