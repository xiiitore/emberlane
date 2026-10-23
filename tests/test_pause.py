import tempfile
import unittest
from pathlib import Path

from emberlane.pause import control_state
from emberlane.planner import GoalPlanner
from emberlane.queue import TaskQueue
from emberlane.worker import LocalWorker


class ControlMarkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / ".emberlane").mkdir()

    def test_control_state_reports_pause_and_stop_with_stop_precedence(self):
        marker_dir = self.root / ".emberlane"
        self.assertIsNone(control_state(self.root))
        (marker_dir / "PAUSED").write_text("pause", encoding="utf-8")
        self.assertEqual(control_state(self.root), "paused")
        (marker_dir / "STOP").write_text("stop", encoding="utf-8")
        self.assertEqual(control_state(self.root), "stopped")

    def test_worker_does_not_claim_pending_tasks_while_paused_or_stopped(self):
        for marker in ("PAUSED", "STOP"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "project"
                root.mkdir()
                worker = LocalWorker(root)
                task = worker.submit("list_files", {})
                marker_path = root / ".emberlane" / marker
                marker_path.write_text(marker.lower(), encoding="utf-8")

                self.assertIsNone(worker.run_one())
                self.assertEqual(worker.queue.get(task.task_id).status, "pending")

    def test_planner_does_not_enqueue_steps_when_paused(self):
        queue = TaskQueue(self.root / ".emberlane" / "queue.json")
        planner = GoalPlanner(queue, {"list_files"}, root=self.root)
        (self.root / ".emberlane" / "PAUSED").write_text("pause", encoding="utf-8")

        result = planner.advance({
            "goal_id": "paused-goal",
            "steps": [{"id": "one", "kind": "list_files", "payload": {}}],
        })

        self.assertEqual(result["status"], "paused")
        self.assertEqual(queue.list_tasks(), [])

    def test_planner_stops_scheduling_between_steps_when_stop_appears(self):
        queue = TaskQueue(self.root / ".emberlane" / "queue.json")
        planner = GoalPlanner(queue, {"list_files"}, root=self.root)
        original_submit = queue.submit
        stop_marker = self.root / ".emberlane" / "STOP"

        def submit(kind, payload, *, idempotency_key=None):
            task = original_submit(kind, payload, idempotency_key=idempotency_key)
            if idempotency_key == "goal:mid-stop:step:first":
                stop_marker.write_text("stop", encoding="utf-8")
            return task

        queue.submit = submit
        result = planner.advance({
            "goal_id": "mid-stop",
            "max_steps_per_cycle": 2,
            "max_cycles": 2,
            "steps": [
                {"id": "first", "kind": "list_files", "payload": {}},
                {"id": "second", "kind": "list_files", "payload": {}},
            ],
        })

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["scheduled"], ["first"])
        self.assertEqual([task.idempotency_key for task in queue.list_tasks()],
                         ["goal:mid-stop:step:first"])


if __name__ == "__main__":
    unittest.main()
