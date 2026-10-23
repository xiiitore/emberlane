import json
import tempfile
import unittest
from pathlib import Path

from emberlane import TaskQueue


class TaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state" / "queue.json"

    def test_submit_survives_restart(self):
        queue = TaskQueue(self.state)
        task = queue.submit("echo", {"value": 7})
        restored = TaskQueue(self.state)
        self.assertEqual(restored.get(task.task_id).payload, {"value": 7})
        self.assertEqual(restored.get(task.task_id).status, "pending")

    def test_running_task_is_recovered_after_restart(self):
        queue = TaskQueue(self.state)
        task = queue.submit("echo", {"value": 7})
        raw = json.loads(self.state.read_text(encoding="utf-8"))
        raw[0]["status"] = "running"
        raw[0]["attempts"] = 1
        self.state.write_text(json.dumps(raw), encoding="utf-8")
        restored = TaskQueue(self.state)
        recovered = restored.get(task.task_id)
        self.assertEqual(recovered.status, "pending")
        self.assertEqual(recovered.attempts, 1)
        self.assertIn("Recovered after interrupted run", recovered.last_error)
        result = restored.run_one({"echo": lambda payload: None})
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.attempts, 2)

    def test_idempotent_submit_returns_existing_task(self):
        queue = TaskQueue(self.state)
        first = queue.submit("write_file", {"path": "x.py", "content": "X = 1"},
                             idempotency_key="github-comment-123")
        duplicate = queue.submit("write_file", {"path": "x.py", "content": "X = 1"},
                                 idempotency_key="github-comment-123")
        self.assertEqual(duplicate.task_id, first.task_id)
        self.assertEqual(len(queue.list_tasks()), 1)

    def test_idempotency_key_cannot_be_reused_for_different_task(self):
        queue = TaskQueue(self.state)
        queue.submit("write_file", {"path": "x.py", "content": "X = 1"},
                     idempotency_key="github-comment-123")
        with self.assertRaisesRegex(ValueError, "different task"):
            queue.submit("write_file", {"path": "x.py", "content": "X = 2"},
                         idempotency_key="github-comment-123")
        self.assertEqual(len(queue.list_tasks()), 1)

    def test_idempotency_survives_restart(self):
        queue = TaskQueue(self.state)
        first = queue.submit("write_file", {"path": "x.py", "content": "X = 1"},
                             idempotency_key="github-comment-123")
        restored = TaskQueue(self.state)
        duplicate = restored.submit("write_file", {"path": "x.py", "content": "X = 1"},
                                    idempotency_key="github-comment-123")
        self.assertEqual(duplicate.task_id, first.task_id)
        self.assertEqual(len(restored.list_tasks()), 1)

    def test_registered_handler_completes_task(self):
        queue = TaskQueue(self.state)
        task = queue.submit("echo", {"value": 7})
        seen = []
        result = queue.run_one({"echo": lambda payload: seen.append(payload["value"])})
        self.assertEqual(seen, [7])
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "completed")

    def test_failure_retries_then_fails(self):
        queue = TaskQueue(self.state, max_attempts=2)
        queue.submit("bad", {})
        handler = {"bad": lambda payload: (_ for _ in ()).throw(RuntimeError("expected"))}
        first = queue.run_one(handler)
        self.assertEqual(first.status, "pending")
        second = queue.run_one(handler)
        self.assertEqual(second.status, "failed")
        self.assertEqual(second.attempts, 2)

        class ChatGPTAgentToolRateLimitException(RuntimeError):
            pass

        deferred = queue.submit("provider", {})
        waiting = queue.run_one({
            "provider": lambda payload: (_ for _ in ()).throw(
                ChatGPTAgentToolRateLimitException("usage limit reached")
            )
        })
        self.assertEqual(waiting.task_id, deferred.task_id)
        self.assertEqual(waiting.status, "deferred")
        self.assertEqual(waiting.attempts, 1)
        self.assertIsNone(waiting.last_error)
        self.assertEqual(waiting.result["reason"], "external_capacity_limit")
        resumed = queue.resume_deferred(waiting.task_id)
        self.assertEqual(resumed.status, "pending")
        completed = queue.run_one({"provider": lambda payload: {"ok": True}})
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.attempts, 2)

    def test_local_model_failure_statuses_do_not_complete_tasks(self):
        queue = TaskQueue(self.state)
        failure_statuses = (
            "model_not_configured", "model_not_found", "input_limit",
            "rejected", "backend_unavailable", "timeout", "output_limit",
            "model_failed", "invalid_model_output", "blocked", "no_changes",
            "snapshot_failed", "verification_setup_failed", "patch_rejected",
            "verification_failed", "tests_missing", "tests_failed", "conflict",
            "apply_failed", "apply_verification_failed", "recovery_required",
        )
        for status in failure_statuses:
            task = queue.submit("local_model", {"status": status})
            result = queue.run_one({
                "local_model": lambda payload: {"status": payload["status"]}
            })
            self.assertEqual(result.task_id, task.task_id, status)
            self.assertEqual(result.status, "failed", status)

    def test_paused_local_model_result_is_deferred_not_completed(self):
        queue = TaskQueue(self.state)
        task = queue.submit("local_model", {"status": "paused"})
        result = queue.run_one({
            "local_model": lambda payload: {"status": payload["status"]}
        })
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "deferred")
    def test_successful_local_model_status_is_not_misclassified(self):
        queue = TaskQueue(self.state)
        task = queue.submit("local_model", {"status": "applied_and_verified"})
        result = queue.run_one({
            "local_model": lambda payload: {"status": payload["status"]}
        })
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "completed")
    def test_unknown_handler_fails_closed(self):
        queue = TaskQueue(self.state)
        queue.submit("unregistered", {})
        result = queue.run_one({})
        self.assertEqual(result.status, "failed")
        self.assertIn("no handler", result.last_error)

    def test_rejects_bad_arguments(self):
        queue = TaskQueue(self.state)
        with self.assertRaises(ValueError):
            queue.submit("", {})
        with self.assertRaises(ValueError):
            queue.submit("ok", [])


if __name__ == "__main__":
    unittest.main()
