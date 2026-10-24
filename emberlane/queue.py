"""Minimal file-backed task queue with atomic state persistence."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None
    import msvcrt
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


def _write_private_archive(path: Path, data: bytes) -> None:
    """Create a new owner-only archive and durably write its exact bytes."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if fd >= 0:
            os.close(fd)
        path.unlink(missing_ok=True)
        raise


_FAILURE_STATES = {
    "failed", "error", "blocked", "cancelled", "canceled", "timeout",
    "rejected", "invalid_model_output", "input_limit", "model_not_configured",
    "model_not_found", "model_unreadable", "model_cli_not_found",
    "model_cli_not_executable", "runtime_loader_failed", "model_load_failed",
    "backend_unavailable", "model_failed", "output_limit", "stderr_limit",
    "empty_model_output", "no_changes", "snapshot_failed",
    "verification_setup_failed", "patch_rejected",
    "verification_failed", "tests_missing", "tests_failed", "conflict",
    "apply_failed", "apply_verification_failed", "recovery_required",
}
_FAILURE_FLAGS = {"ok", "success", "passed", "synced", "applied", "verified"}


def _is_external_wait_exception(exc: Exception) -> bool:
    """Identify known quota/capacity waits without treating arbitrary errors as waits."""
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    if name in {
        "chatgptagenttoolratelimitexception",
        "ratelimiterror",
        "quotaexceedederror",
        "usage_limit_error",
    }:
        return True
    return any(marker in message for marker in (
        "chatgptagenttoolratelimit",
        "rate limit exceeded",
        "rate limit reached",
        "usage limit reached",
        "usage limit exceeded",
        "quota exceeded",
        "too many requests",
        "http 429",
    ))


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
    """File-backed queue serialized across processes with an OS lock.

    The lock covers each complete queue operation, including handler execution.
    This intentionally favors correctness over concurrent submissions during a
    long-running handler. Handler side effects remain at-least-once after a crash.
    """

    def __init__(self, state_path: str | Path, max_attempts: int = 3):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.state_path = Path(state_path)
        self.max_attempts = max_attempts
        self.lock_timeout_seconds = 15.0
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, Task] = {}
        # Nested queue calls from a handler (for example GoalPlanner.advance ->
        # queue.submit) must reuse the outer lock and its in-memory snapshot.
        self._thread_lock = threading.RLock()
        self._lock_depth = 0
        with self._locked_refresh():
            pass

    @contextmanager
    def _locked_refresh(self) -> Iterator[None]:
        """Refresh under bounded thread/OS locks; reuse both for nested calls.

        The lock file is never replaced or removed: queue.json itself is atomically
        replaced by _save(), so locking queue.json would not serialize processes
        that opened different inodes. Locks are advisory and require a filesystem
        that implements POSIX flock or Windows byte-range locking correctly.

        Reentrant calls from the same thread must not open a second descriptor or
        reload state while a handler is executing.
        """
        if not self._thread_lock.acquire(timeout=self.lock_timeout_seconds):
            raise TimeoutError("timed out acquiring in-process queue lock")
        try:
            if self._lock_depth:
                self._lock_depth += 1
                try:
                    yield
                finally:
                    self._lock_depth -= 1
                return

            lock_path = self.state_path.with_name(self.state_path.name + ".lock")
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            locked = False
            try:
                if fcntl is None:  # pragma: no cover - exercised on Windows
                    if os.fstat(fd).st_size == 0:
                        os.write(fd, b"\\0")
                        os.fsync(fd)
                deadline = time.monotonic() + self.lock_timeout_seconds
                while True:
                    try:
                        if fcntl is not None:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        else:  # pragma: no cover - exercised on Windows
                            os.lseek(fd, 0, os.SEEK_SET)
                            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except (BlockingIOError, OSError) as exc:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                f"timed out acquiring queue lock: {lock_path.name}"
                            ) from exc
                        time.sleep(0.025)
                self._lock_depth = 1
                self._load()
                yield
            finally:
                self._lock_depth = 0
                if locked:
                    if fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    else:  # pragma: no cover - exercised on Windows
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                os.close(fd)
        finally:
            self._thread_lock.release()

    def _load(self) -> None:
        self._tasks = {}
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
                if task.attempts >= self.max_attempts:
                    task.status = "failed"
                    task.last_error = (
                        "Recovered after interrupted run, but retry limit is exhausted; "
                        "manual recovery required because the side effect may have occurred."
                    )
                else:
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
        with self._locked_refresh():
            if idempotency_key is not None:
                for existing in self._tasks.values():
                    if existing.idempotency_key == idempotency_key:
                        if existing.kind != kind or existing.payload != payload:
                            raise ValueError("idempotency key already used for a different task")
                        return copy.deepcopy(existing)
            now = time.time()
            task = Task(
                str(uuid.uuid4()), kind, copy.deepcopy(payload),
                created_at=now, updated_at=now,
                idempotency_key=idempotency_key,
            )
            self._tasks[task.task_id] = task
            self._save()
            return copy.deepcopy(task)

    def get(self, task_id: str) -> Task | None:
        with self._locked_refresh():
            task = self._tasks.get(task_id)
            return copy.deepcopy(task) if task is not None else None

    def list_tasks(self) -> list[Task]:
        with self._locked_refresh():
            return copy.deepcopy(list(self._tasks.values()))

    def resume_deferred(self, task_id: str) -> Task:
        """Explicitly requeue a deferred task after its external dependency recovers."""
        with self._locked_refresh():
            return copy.deepcopy(self._resume_deferred_locked(task_id))

    def _resume_deferred_locked(self, task_id: str) -> Task:
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

    def prune_terminal(self, keep_terminal: int = 50) -> dict[str, Any]:
        with self._locked_refresh():
            return self._prune_terminal_locked(keep_terminal)

    def _prune_terminal_locked(self, keep_terminal: int = 50) -> dict[str, Any]:
        """Archive the current queue, then remove only old terminal tasks.

        Pending, running and deferred tasks are always preserved. A local backup
        is written before the atomic queue rewrite; no task payload is published.
        """
        if isinstance(keep_terminal, bool) or not isinstance(keep_terminal, int):
            raise ValueError("keep_terminal must be an integer")
        if not 0 <= keep_terminal <= 1000:
            raise ValueError("keep_terminal must be from 0 to 1000")

        terminal_states = {"completed", "failed", "cancelled", "canceled"}
        terminal = sorted(
            (task for task in self._tasks.values() if task.status in terminal_states),
            key=lambda task: (task.updated_at, task.created_at, task.task_id),
        )
        remove_count = max(0, len(terminal) - keep_terminal)
        to_remove = terminal[:remove_count]
        if not to_remove:
            return {
                "pruned_count": 0,
                "kept_terminal_count": len(terminal),
                "preserved_active_count": sum(
                    task.status not in terminal_states for task in self._tasks.values()
                ),
                "backup_file": None,
            }

        backup_path = self.state_path.with_name(
            f"{self.state_path.name}.pre-prune-{time.time_ns()}.bak"
        )
        if self.state_path.exists():
            state_bytes = self.state_path.read_bytes()
            _write_private_archive(backup_path, state_bytes)
            # Pruning is destructive to historical records: verify the recovery
            # copy byte-for-byte before changing in-memory or persisted queue state.
            if backup_path.read_bytes() != state_bytes:
                raise OSError("queue archive verification failed; queue was not pruned")
        else:
            raise FileNotFoundError("queue state file disappeared before archival")

        original_tasks = self._tasks.copy()
        for task in to_remove:
            del self._tasks[task.task_id]
        try:
            self._save()
        except BaseException:
            self._tasks = original_tasks
            raise
        return {
            "pruned_count": len(to_remove),
            "kept_terminal_count": len(terminal) - len(to_remove),
            "preserved_active_count": sum(
                task.status not in terminal_states for task in self._tasks.values()
            ),
            "backup_file": backup_path.name,
        }

    def run_one(self, handlers: dict[str, Callable[[dict[str, Any]], Any]]) -> Task | None:
        with self._locked_refresh():
            task = next((t for t in self._tasks.values() if t.status == "pending"), None)
            if task is None:
                return None
            return copy.deepcopy(self._run_task(task, handlers))

    def run_task(
        self,
        task_id: str,
        handlers: dict[str, Callable[[dict[str, Any]], Any]],
    ) -> Task | None:
        """Run only the requested pending task; never substitute another queue item."""
        with self._locked_refresh():
            task = self._tasks.get(task_id)
            if task is None or task.status != "pending":
                return None
            return self._run_task(task, handlers)

    def _run_task(
        self,
        task: Task,
        handlers: dict[str, Callable[[dict[str, Any]], Any]],
    ) -> Task:
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
            if result_status in {"deferred", "waiting_for_quota", "rate_limited", "paused", "stopped"}:
                task.last_error = None
                task.status = "deferred"
            elif _result_has_failure(task.result):
                task.last_error = "handler returned explicit failure evidence"
                task.status = "failed"
            else:
                task.last_error = None
                task.status = "completed"
        task.updated_at = time.time()
        self._save()
        return task
