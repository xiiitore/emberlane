import tempfile
import unittest
from pathlib import Path

from emberlane.planner import GoalPlanner, PlanValidationError
from emberlane.queue import TaskQueue


class GoalPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue = TaskQueue(Path(self.temp.name) / "queue.json")
        self.planner = GoalPlanner(self.queue, {"write_file", "run_tests", "diagnostics"})

    def plan(self, **overrides):
        payload = {
            "goal_id": "test-goal",
            "steps": [
                {"id": "inspect", "kind": "diagnostics", "payload": {}},
                {"id": "edit", "kind": "write_file",
                 "payload": {"path": "out.txt", "content": "ok"},
                 "depends_on": ["inspect"]},
                {"id": "verify", "kind": "run_tests", "payload": {},
                 "depends_on": ["edit"]},
            ],
            "max_steps_per_cycle": 1,
            "max_cycles": 10,
        }
        payload.update(overrides)
        return payload

    def test_schedules_only_ready_steps_and_continuation(self):
        result = self.planner.advance(self.plan())
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["scheduled"], ["inspect"])
        tasks = self.queue.list_tasks()
        self.assertEqual(tasks[0].kind, "diagnostics")
        self.assertEqual(tasks[1].kind, "plan_goal")
        self.assertEqual(tasks[0].idempotency_key, "goal:test-goal:step:inspect")

    def test_idempotency_prevents_duplicate_step(self):
        self.planner.advance(self.plan())
        before = len(self.queue.list_tasks())
        # Repeated call does not duplicate the already-enqueued first step.
        result = self.planner.advance(self.plan(cycle=1))
        self.assertEqual(result["scheduled"], [])
        self.assertEqual(len(self.queue.list_tasks()), before + 1)  # continuation only

    def test_dependency_unlocks_after_completion(self):
        first = self.planner.advance(self.plan())
        self.queue.run_one({"diagnostics": lambda payload: {"ok": True}})
        # Remove the continuation from consideration to exercise a deterministic tick.
        continuation = next(t for t in self.queue.list_tasks() if t.kind == "plan_goal")
        continuation.status = "completed"
        self.queue._save()
        result = self.planner.advance(self.plan(cycle=1))
        self.assertEqual(result["scheduled"], ["edit"])

    def test_rejects_unknown_task_kind_before_enqueuing(self):
        with self.assertRaisesRegex(PlanValidationError, "not allowed"):
            self.planner.advance(self.plan(steps=[{"id": "bad", "kind": "shell", "payload": {}}]))
        self.assertEqual(self.queue.list_tasks(), [])

    def test_rejects_dependency_cycles_before_enqueuing(self):
        with self.assertRaisesRegex(PlanValidationError, "cycle"):
            self.planner.advance(self.plan(steps=[
                {"id": "a", "kind": "diagnostics", "depends_on": ["b"]},
                {"id": "b", "kind": "run_tests", "depends_on": ["a"]},
            ]))
        self.assertEqual(self.queue.list_tasks(), [])

    def test_stops_after_failed_step(self):
        self.planner.advance(self.plan())
        task = next(t for t in self.queue.list_tasks() if t.kind == "diagnostics")
        task.status = "failed"
        self.queue._save()
        result = self.planner.advance(self.plan(cycle=1))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["scheduled"], [])
        self.assertEqual(result["failed_steps"], ["inspect"])

    def test_validates_cycle_and_batch_limits(self):
        with self.assertRaisesRegex(PlanValidationError, "max_steps_per_cycle"):
            self.planner.advance(self.plan(max_steps_per_cycle=11))
        with self.assertRaisesRegex(PlanValidationError, "cycle"):
            self.planner.advance(self.plan(cycle=11))

    def test_no_extra_continuation_after_completion(self):
        result = self.planner.advance(self.plan(steps=[
            {"id": "one", "kind": "diagnostics", "payload": {}}
        ], max_steps_per_cycle=1))
        self.assertEqual(result["status"], "active")
        task = self.queue.get(result["next_cycle_task_id"])
        self.assertIsNotNone(task)
        self.queue.run_one({"diagnostics": lambda payload: {"ok": True}})
        task.status = "completed"
        self.queue._save()
        result = self.planner.advance(self.plan(steps=[
            {"id": "one", "kind": "diagnostics", "payload": {}}
        ], cycle=1, max_steps_per_cycle=1))
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["next_cycle_task_id"])


if __name__ == "__main__":
    unittest.main()
