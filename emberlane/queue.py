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

    def submit(self, kind: str, payload: dict[str, Any]) -> Task:
        if not kind or not isinstance(kind, str):
            raise ValueError("kind must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dictionary")
        now = time.time()
        task = Task(str(uuid.uuid4()), kind, payload, created_at=now, updated_at=now)
        self._tasks[task.task_id] = task
        self._save()
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[Task]:
        return list(self._tasks.values())

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
            task.result = None
            task.last_error = f"{type(exc).__name__}: {exc}"
            task.status = "pending" if task.attempts < self.max_attempts else "failed"
        else:
            task.last_error = None
            task.status = "completed"
        task.updated_at = time.time()
        self._save()
        return task
