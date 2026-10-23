"""Bounded, dependency-aware goal planning over the existing TaskQueue.

Plans are declarative allow-listed task steps. The planner never executes commands
itself; it submits work to the worker's existing handler registry and queue.
"""
from __future__ import annotations

from typing import Any

from .queue import TaskQueue

MAX_PLAN_STEPS = 50
MAX_STEPS_PER_CYCLE = 10
MAX_PLAN_CYCLES = 50
MAX_FAILURES = 5

_FAILURE_STATES = {"failed", "error", "blocked", "cancelled", "canceled", "timeout"}
_FAILURE_FLAGS = {"ok", "success", "passed", "synced", "applied", "verified"}


def _result_has_failure(value: Any) -> bool:
    """Detect explicit failure evidence in a handler's JSON-compatible result.

    Queue status "completed" means the handler returned without raising; it does
    not prove that the operation succeeded. Inspect structured result evidence
    (including nested command/test summaries) before unlocking dependent steps.
    """
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


def _task_succeeded(task: Any) -> bool:
    """True only when execution completed without explicit result-level failure."""
    return task.status == "completed" and not _result_has_failure(task.result)


def _task_failed(task: Any) -> bool:
    """Treat both executor exceptions and returned failure evidence as failures."""
    return task.status == "failed" or (
        task.status == "completed" and _result_has_failure(task.result)
    )


class PlanValidationError(ValueError):
    """Raised when a goal plan is malformed or unsafe."""


class GoalPlanner:
    def __init__(self, queue: TaskQueue, allowed_kinds: set[str]):
        self.queue = queue
        self.allowed_kinds = set(allowed_kinds)

    @staticmethod
    def _bounded_int(value: Any, name: str, low: int, high: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PlanValidationError(f"{name} must be an integer from {low} to {high}")
        return value

    def advance(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal_id = payload.get("goal_id")
        steps = payload.get("steps")
        if not isinstance(goal_id, str) or not goal_id.strip() or len(goal_id) > 120:
            raise PlanValidationError("goal_id must be a non-empty string of at most 120 characters")
        if not isinstance(steps, list) or not steps or len(steps) > MAX_PLAN_STEPS:
            raise PlanValidationError(f"steps must be a list containing 1 to {MAX_PLAN_STEPS} steps")

        max_steps = self._bounded_int(payload.get("max_steps_per_cycle", 3),
                                      "max_steps_per_cycle", 1, MAX_STEPS_PER_CYCLE)
        max_failures = self._bounded_int(payload.get("max_failures", 2),
                                         "max_failures", 1, MAX_FAILURES)
        max_cycles = self._bounded_int(payload.get("max_cycles", 20),
                                       "max_cycles", 1, MAX_PLAN_CYCLES)
        cycle = self._bounded_int(payload.get("cycle", 0), "cycle", 0, max_cycles)
        normalized: dict[str, dict[str, Any]] = {}

        for step in steps:
            if not isinstance(step, dict):
                raise PlanValidationError("each step must be an object")
            step_id, kind, step_payload = step.get("id"), step.get("kind"), step.get("payload", {})
            deps = step.get("depends_on", [])
            if not isinstance(step_id, str) or not step_id or len(step_id) > 120:
                raise PlanValidationError("each step id must be a non-empty string of at most 120 characters")
            if step_id in normalized:
                raise PlanValidationError(f"duplicate step id: {step_id}")
            if not isinstance(kind, str) or kind not in self.allowed_kinds:
                raise PlanValidationError(f"step {step_id} uses a task kind that is not allowed")
            if not isinstance(step_payload, dict):
                raise PlanValidationError(f"step {step_id} payload must be an object")
            if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
                raise PlanValidationError(f"step {step_id} depends_on must be a list of step ids")
            if step_id in deps or len(set(deps)) != len(deps):
                raise PlanValidationError(f"step {step_id} has a self-dependency or duplicate dependency")
            normalized[step_id] = {
                "id": step_id, "kind": kind, "payload": step_payload, "depends_on": deps
            }

        for step in normalized.values():
            unknown = set(step["depends_on"]) - set(normalized)
            if unknown:
                raise PlanValidationError(
                    f"step {step['id']} has unknown dependencies: {', '.join(sorted(unknown))}"
                )

        # Reject cycles before enqueuing any side effect.
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise PlanValidationError("plan contains a dependency cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dep in normalized[step_id]["depends_on"]:
                visit(dep)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in normalized:
            visit(step_id)

        key_prefix = f"goal:{goal_id}:step:"
        existing = {
            task.idempotency_key[len(key_prefix):]: task
            for task in self.queue.list_tasks()
            if task.idempotency_key and task.idempotency_key.startswith(key_prefix)
        }
        for step_id, step in normalized.items():
            prior = existing.get(step_id)
            if prior is not None and (prior.kind != step["kind"] or prior.payload != step["payload"]):
                raise PlanValidationError(
                    f"step {step_id} conflicts with a previously queued task; use a new goal_id"
                )

        failed = [step_id for step_id, task in existing.items() if _task_failed(task)]
        if len(failed) >= max_failures:
            return {
                "goal_id": goal_id, "status": "blocked", "cycle": cycle,
                "reason": "failure_limit_reached", "failed_steps": sorted(failed),
                "scheduled": [], "completed_steps": self._completed(existing),
            }

        for step_id in failed:
            if step_id in normalized:
                return {
                    "goal_id": goal_id, "status": "blocked", "cycle": cycle,
                    "reason": "dependency_or_step_failed", "failed_steps": sorted(failed),
                    "scheduled": [], "completed_steps": self._completed(existing),
                }

        scheduled: list[str] = []
        for step_id, step in normalized.items():
            if step_id in existing:
                continue
            dep_tasks = [existing.get(dep) for dep in step["depends_on"]]
            if any(task is None or not _task_succeeded(task) for task in dep_tasks):
                continue
            if len(scheduled) >= max_steps:
                break
            task = self.queue.submit(
                step["kind"], step["payload"],
                idempotency_key=f"{key_prefix}{step_id}",
            )
            existing[step_id] = task
            scheduled.append(step_id)

        completed = self._completed(existing)
        failed = sorted(step_id for step_id, task in existing.items() if _task_failed(task))
        all_completed = len(completed) == len(normalized)
        if all_completed:
            status = "completed"
        elif failed:
            status = "blocked"
        else:
            status = "active"

        next_cycle_task_id = None
        # Continuations are queued after the tasks scheduled this cycle, so the
        # worker drains ready work before the planner evaluates dependencies again.
        if status == "active" and cycle < max_cycles:
            next_task = self.queue.submit(
                "plan_goal",
                {**payload, "cycle": cycle + 1},
                idempotency_key=f"goal:{goal_id}:planner:cycle:{cycle + 1}",
            )
            next_cycle_task_id = next_task.task_id
        elif status == "active" and cycle >= max_cycles:
            status = "blocked"

        return {
            "goal_id": goal_id,
            "status": status,
            "cycle": cycle,
            "scheduled": scheduled,
            "completed_steps": completed,
            "failed_steps": failed,
            "next_cycle_task_id": next_cycle_task_id,
            "limits": {
                "max_steps_per_cycle": max_steps,
                "max_cycles": max_cycles,
                "max_failures": max_failures,
            },
        }

    @staticmethod
    def _completed(existing: dict[str, Any]) -> list[str]:
        return sorted(step_id for step_id, task in existing.items() if _task_succeeded(task))
