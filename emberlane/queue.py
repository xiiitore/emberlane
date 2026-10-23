"""Minimal file-backed task queue with atomic state persistence."""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


_FAILURE_STATES = {"failed", "error", "blocked", "cancelled", "canceled", "timeout"}
_FAILURE_FLAGS = {"ok", "success", "passed", "synced", "applied", "verified"}


def _is_external_wait_exception(exc: Exception) -> bool:
    """Identify known quota/capacity waits without treating arbitrary errors as waits."""
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    known_names = {
        "chatgptagenttoolratelimitexception",
        "ratelimiterror",
        "quotaexceedederror",
        "usage_limit_error",
    }
    if name in known_names:
        return True
    markers = (
        "chatgptagenttoolratelimit",
        "rate limit exceeded",
        "rate limit reached",
        "usage limit reached",
        "usage limit exceeded",
        "quota exceeded",
        "resource exhausted",
        "too many requests",
        "http 429",
    )
    return any(marker in message for marker in markers)


def _result_has_failure(value: Any) -> bool:
    """Recognize explicit failure evidence in a JSON-compatible handler result."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = key.lower() if isinstance(key, str) else key
            if normalized_key in _FAILURE_FLAGS and item is False:
                return True
            if normalized_key in {"status", "state"} and isinstance(item, str):
                if item.strip().lower() in _FAILURE_STATES:
                    return True
            if normalized_key in {"returncode", "exit_code"}:
                if isinstance(item, int) and not isinstance(item, bool) and item != 0:
                    return True
            if normalized_key == "error" and item not in (None, "", False):
                return True
            if _result_has_failure(item):
                return True
    elif isinstance(value, list):
        return any(_result_has_failure(item) for item in value)
    return False


@dataclass
class Task:
    task_id: str
    kind: str
    payload: dict[str, Any]
    status: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    idempotency_key: str | None = None
    result: Any = None


class TaskQueue:
    """A small single-process queue. Not intended for concurrent writers."""

    def __init__(self, state_path: str | Path, max_attempts: int = 3):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.state_path = Path(state_path)
        self.max_attempts = max_attempts
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, Task] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("state file must contain a JSON list")
        loaded: dict[str, Task] = {}
        for item in raw:
            task = Task(**item)
            if task.task_id in loaded:
                raise ValueError("duplicate task id in state file")
            loaded[task.task_id] = task
        self._tasks = loaded
        # A process may have stopped after persisting "running" but before
        # persisting a terminal state. Requeue it on restart. This is
        # at-least-once behavior: a handler may run again if it performed its
        # side effect before the process stopped.
        recovered = False
        now = time.time()
        for task in self._tasks.values():
            if task.status == "running":
                task.status = "pending"
                task.last_error = (
                    "Recovered after interrupted run; handler may be retried."
                )
                task.updated_at = now
                recovered = True
        if recovered:
            self._save()

    def _save(self) -> None:
        data = [asdict(task) for task in self._tasks.values()]
        fd, temporary = tempfile.mkstemp(prefix=".queue-", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> Task:
        if not kind or not isinstance(kind, str):
            raise ValueError("kind must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key:
                raise ValueError("idempotency_key must be a non-empty string")
            for existing in self._tasks.values():
                if existing.idempotency_key == idempotency_key:
                    if existing.kind != kind or existing.payload != payload:
                        raise ValueError("idempotency key already used for a different task")
                    return existing
        now = time.time()
        task = Task(
            str(uuid.uuid4()), kind, payload,
            created_at=now, updated_at=now,
            idempotency_key=idempotency_key,
        )
        self._tasks[task.task_id] = task
        self._save()
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[Task]:
        return list(self._tasks.values())

    def resume_deferred(self, task_id: str) -> Task:
        """Explicitly requeue a deferred task after its external dependency recovers."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task id: {task_id}")
        if task.status != "deferred":
            raise ValueError(f"task is not deferred: {task_id}")
        task.status = "pending"
        task.last_error = None
        task.result = None
        task.updated_at = time.time()
        self._save()
        return task

    def run_one(self, handlers: dict[str, Callable[[dict[str, Any]], Any]]) -> Task | None:
        task = next((t for t in self._tasks.values() if t.status == "pending"), None)
        if task is None:
            return None
        handler = handlers.get(task.kind)
        if handler is None:
            task.status = "failed"
            task.last_error = f"no handler registered for kind: {task.kind}"
            task.updated_at = time.time()
            self._save()
            return task
        task.status = "running"
        task.attempts += 1
        task.updated_at = time.time()
        self._save()
        try:
            # Persist only JSON-compatible results so task state remains portable.
            task.result = json.loads(json.dumps(handler(task.payload), ensure_ascii=False))
        except Exception as exc:
            if _is_external_wait_exception(exc):
                # Known provider quota/usage limits are external waits, not code
                # defects. Persist a safe marker and stop retrying this task.
                task.result = {
                    "status": "deferred",
                    "reason": "external_capacity_limit",
                    "exception_type": type(exc).__name__,
                }
                task.last_error = None
                task.status = "deferred"
            else:
                task.result = None
                task.last_error = f"{type(exc).__name__}: {exc}"
                task.status = "pending" if task.attempts < self.max_attempts else "failed"
        else:
            result_status = (
                task.result.get("status", "").strip().lower()
                if isinstance(task.result, dict)
                and isinstance(task.result.get("status"), str)
                else ""
            )
            if result_status in {"deferred", "waiting_for_quota", "rate_limited"}:
                # External capacity limits are waiting states, not code failures.
                # Do not retry automatically or label the task successful.
                task.last_error = None
                task.status = "deferred"
            elif _result_has_failure(task.result):
                # A handler may return normally while reporting a failed operation.
                # Preserve its structured result, but do not label the task successful.
                task.last_error = "handler returned explicit failure evidence"
                task.status = "failed"
            else:
                task.last_error = None
                task.status = "completed"
        task.updated_at = time.time()
        self._save()
        return task
