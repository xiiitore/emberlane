import json
import threading
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
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

    def test_recovered_running_task_at_attempt_limit_fails_closed(self):
        queue = TaskQueue(self.state, max_attempts=1)
        task = queue.submit("side_effect", {"value": "may-have-run"})
        raw = json.loads(self.state.read_text(encoding="utf-8"))
        raw[0]["status"] = "running"
        raw[0]["attempts"] = 1
        self.state.write_text(json.dumps(raw), encoding="utf-8")

        restored = TaskQueue(self.state, max_attempts=1)
        recovered = restored.get(task.task_id)
        self.assertEqual(recovered.status, "failed")
        self.assertIn("retry limit is exhausted", recovered.last_error)
        self.assertIn("manual recovery required", recovered.last_error)

        called = []
        self.assertIsNone(restored.run_one({"side_effect": lambda payload: called.append(payload)}))
        self.assertEqual(called, [])

    def test_lock_wait_is_bounded_for_a_second_queue_instance(self):
        queue = TaskQueue(self.state)
        other = TaskQueue(self.state)
        other.lock_timeout_seconds = 0.1
        queue.submit("parent", {})

        def handler(payload):
            other.submit("child", {})
            return {"ok": True}

        result = queue.run_one({"parent": handler})
        self.assertEqual(result.status, "pending")
        self.assertIn("timed out acquiring queue lock", result.last_error)
        self.assertEqual(len(queue.list_tasks()), 1)

    def test_in_process_lock_wait_is_bounded(self):
        queue = TaskQueue(self.state)
        queue.lock_timeout_seconds = 0.05
        acquired = threading.Event()
        release = threading.Event()

        def hold_lock():
            queue._thread_lock.acquire()
            try:
                acquired.set()
                release.wait(timeout=2)
            finally:
                queue._thread_lock.release()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.assertTrue(acquired.wait(timeout=1))
        try:
            with self.assertRaisesRegex(TimeoutError, "in-process queue lock"):
                queue.list_tasks()
        finally:
            release.set()
            holder.join(timeout=2)
        self.assertFalse(holder.is_alive())

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
    def test_forced_process_exit_recovers_running_task_on_restart(self):
        repo_root = Path(__file__).resolve().parents[1]
        child_code = (
            "import os, sys\n"
            "from emberlane import TaskQueue\n"
            "queue = TaskQueue(sys.argv[1])\n"
            "task = queue.submit('crash_after_claim', {'value': 7})\n"
            "print(task.task_id, flush=True)\n"
            "queue.run_one({'crash_after_claim': lambda payload: os._exit(77)})\n"
        )
        crashed = subprocess.run(
            [sys.executable, "-c", child_code, str(self.state)],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
            shell=False,
        )
        self.assertEqual(crashed.returncode, 77, crashed.stderr)
        task_id = crashed.stdout.strip()
        self.assertTrue(task_id)

        recovered = TaskQueue(self.state)
        task = recovered.get(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.attempts, 1)
        self.assertIn("Recovered after interrupted run", task.last_error)

        completed = recovered.run_one({"crash_after_claim": lambda payload: {"ok": True, "value": payload["value"]}})
        self.assertEqual(completed.task_id, task_id)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.attempts, 2)
        self.assertEqual(completed.result, {"ok": True, "value": 7})

    def test_deferred_quota_survives_restart_without_retry_until_explicit_resume(self):
        class ChatGPTAgentToolRateLimitException(RuntimeError):
            pass

        queue = TaskQueue(self.state)
        submitted = queue.submit("provider", {"request": "bounded"})
        first = queue.run_one({
            "provider": lambda payload: (_ for _ in ()).throw(
                ChatGPTAgentToolRateLimitException("usage limit reached")
            )
        })
        self.assertEqual(first.status, "deferred")
        self.assertEqual(first.attempts, 1)

        restored = TaskQueue(self.state)
        deferred = restored.get(submitted.task_id)
        self.assertEqual(deferred.status, "deferred")
        self.assertEqual(deferred.attempts, 1)
        calls = []
        self.assertIsNone(restored.run_one({"provider": lambda payload: calls.append(payload)}))
        self.assertEqual(calls, [])
        self.assertEqual(restored.get(submitted.task_id).attempts, 1)

        resumed = restored.resume_deferred(submitted.task_id)
        self.assertEqual(resumed.status, "pending")
        after_resume = TaskQueue(self.state)
        completed = after_resume.run_one({
            "provider": lambda payload: {"ok": True, "resumed": payload["request"]}
        })
        self.assertEqual(completed.task_id, submitted.task_id)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.attempts, 2)
        self.assertEqual(completed.result, {"ok": True, "resumed": "bounded"})

    def test_unrelated_resource_exhaustion_is_not_deferred_as_quota(self):
        queue = TaskQueue(self.state)
        task = queue.submit("provider", {})

        def fail_for_unrelated_resource_reason(payload):
            raise RuntimeError("resource exhausted while allocating memory")

        statuses = []
        for _ in range(3):
            result = queue.run_one({"provider": fail_for_unrelated_resource_reason})
            self.assertEqual(result.task_id, task.task_id)
            statuses.append(result.status)

        self.assertEqual(statuses, ["pending", "pending", "failed"])
        self.assertNotIn("deferred", statuses)
        self.assertIn("resource exhausted", queue.get(task.task_id).last_error)

    def test_explicit_negative_result_evidence_fails_closed(self):
        queue = TaskQueue(self.state)
        failures = [
            {"ok": False},
            {"passed": False},
            {"status": "failed"},
            {"state": "error"},
            {"returncode": 1},
            {"nested": {"exit_code": 2}},
            {"nested": {"error": "handler failed"}},
        ]
        for index, result_value in enumerate(failures):
            task = queue.submit("result", {"value": result_value, "index": index})
            result = queue.run_one({"result": lambda payload: payload["value"]})
            self.assertEqual(result.task_id, task.task_id)
            self.assertEqual(result.status, "failed", result_value)

    def test_success_metadata_is_not_misclassified_as_failure(self):
        queue = TaskQueue(self.state)
        successful = [
            {"ok": True},
            {"passed": True, "returncode": 0},
            {"status": "completed", "metadata": {"verified": True}},
        ]
        for index, result_value in enumerate(successful):
            task = queue.submit("result", {"value": result_value, "index": index})
            result = queue.run_one({"result": lambda payload: payload["value"]})
            self.assertEqual(result.task_id, task.task_id)
            self.assertEqual(result.status, "completed", result_value)

    def test_returned_rate_limit_status_is_deferred(self):
        queue = TaskQueue(self.state)
        for status in ("deferred", "waiting_for_quota", "rate_limited", "paused"):
            task = queue.submit("result", {"status": status})
            result = queue.run_one({"result": lambda payload: payload})
            self.assertEqual(result.task_id, task.task_id)
            self.assertEqual(result.status, "deferred", status)

    def test_prune_terminal_archives_state_and_preserves_active_tasks(self):
        queue = TaskQueue(self.state)
        completed = queue.submit("done", {})
        failed = queue.submit("bad", {})
        cancelled = queue.submit("cancelled", {})
        pending = queue.submit("pending", {})
        deferred = queue.submit("deferred", {})
        stored_tasks = {task.task_id: task for task in queue.list_tasks()}
        for task, status, stamp in (
            (completed, "completed", 10.0),
            (failed, "failed", 20.0),
            (cancelled, "cancelled", 30.0),
            (pending, "pending", 40.0),
            (deferred, "deferred", 50.0),
        ):
            stored = queue._tasks[task.task_id]
            stored.status = status
            stored.updated_at = stamp
        queue._save()

        result = queue.prune_terminal(keep_terminal=1)

        self.assertEqual(result["pruned_count"], 2)
        self.assertEqual(result["kept_terminal_count"], 1)
        self.assertEqual(result["preserved_active_count"], 2)
        self.assertTrue((self.state.parent / result["backup_file"]).is_file())
        self.assertIsNone(queue.get(completed.task_id))
        self.assertIsNone(queue.get(failed.task_id))
        self.assertIsNotNone(queue.get(cancelled.task_id))
        self.assertEqual(queue.get(pending.task_id).status, "pending")
        self.assertEqual(queue.get(deferred.task_id).status, "deferred")
        archived = json.loads((self.state.parent / result["backup_file"]).read_text(encoding="utf-8"))
        self.assertEqual(len(archived), 5)

        # A second prune is a no-op: it must not create a redundant backup.
        second = queue.prune_terminal(keep_terminal=1)
        self.assertEqual(second["pruned_count"], 0)
        self.assertEqual(second["kept_terminal_count"], 1)
        self.assertEqual(second["preserved_active_count"], 2)
        self.assertIsNone(second["backup_file"])

    @unittest.skipIf(sys.platform == "win32", "POSIX file mode assertion")
    def test_prune_terminal_archive_is_private(self):
        queue = TaskQueue(self.state)
        old = queue.submit("done", {"content": "potentially sensitive payload"})
        queue._tasks[old.task_id].status = "completed"
        queue._tasks[old.task_id].updated_at = 1.0
        queue._save()

        result = queue.prune_terminal(keep_terminal=0)
        backup = self.state.parent / result["backup_file"]

        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_prune_terminal_refuses_to_prune_if_archive_verification_fails(self):
        queue = TaskQueue(self.state)
        old = queue.submit("done", {})
        queue.submit("pending", {})
        old = queue.get(old.task_id)
        queue._tasks[old.task_id].status = "completed"
        queue._tasks[old.task_id].updated_at = 1.0
        queue._save()
        original_state = self.state.read_bytes()
        from emberlane.queue import _write_private_archive as write_private_archive

        def corrupt_archive(path, data):
            return write_private_archive(
                path, b"corrupt archive" if ".pre-prune-" in path.name else data
            )

        with patch("emberlane.queue._write_private_archive", side_effect=corrupt_archive):
            with self.assertRaisesRegex(OSError, "archive verification failed"):
                queue.prune_terminal(keep_terminal=0)

        self.assertEqual(self.state.read_bytes(), original_state)
        self.assertIsNotNone(queue.get(old.task_id))
        self.assertEqual(queue.get(old.task_id).status, "completed")
        self.assertEqual(len(queue.list_tasks()), 2)

    def test_prune_terminal_rejects_invalid_retention_limit(self):
        queue = TaskQueue(self.state)
        with self.assertRaises(ValueError):
            queue.prune_terminal(keep_terminal=True)
        with self.assertRaises(ValueError):
            queue.prune_terminal(keep_terminal=1001)

    def test_unknown_handler_fails_closed(self):
        queue = TaskQueue(self.state)
        queue.submit("unregistered", {})
        result = queue.run_one({})
        self.assertEqual(result.status, "failed")
        self.assertIn("no handler", result.last_error)

    def test_public_task_objects_are_detached_snapshots(self):
        queue = TaskQueue(self.state)
        payload = {"nested": {"value": 1}}
        created = queue.submit("echo", payload, idempotency_key="snapshot-key")
        payload["nested"]["value"] = 9
        self.assertEqual(queue.get(created.task_id).payload, {"nested": {"value": 1}})
        payload["nested"]["value"] = 1
        created.status = "failed"
        created.payload["nested"]["value"] = 2

        fetched = queue.get(created.task_id)
        self.assertEqual(fetched.status, "pending")
        self.assertEqual(fetched.payload, payload)
        fetched.status = "completed"
        fetched.payload["nested"]["value"] = 3

        listed = queue.list_tasks()
        listed[0].status = "failed"
        listed[0].payload["nested"]["value"] = 4
        restored = TaskQueue(self.state)
        final = restored.get(created.task_id)
        self.assertEqual(final.status, "pending")
        self.assertEqual(final.payload, payload)

        duplicate = queue.submit("echo", payload, idempotency_key="snapshot-key")
        duplicate.status = "failed"
        duplicate.payload["nested"]["value"] = 5
        again = queue.submit("echo", payload, idempotency_key="snapshot-key")
        again.status = "completed"
        self.assertEqual(again.task_id, created.task_id)
        self.assertEqual(queue.get(again.task_id).status, "pending")
        self.assertEqual(queue.get(again.task_id).payload, payload)

    def test_handler_cannot_mutate_persisted_task_payload(self):
        queue = TaskQueue(self.state)
        created = queue.submit("mutating", {"nested": {"value": 1}})

        def mutate(payload):
            payload["nested"]["value"] = 99
            return {"ok": True}

        result = queue.run_task(created.task_id, {"mutating": mutate})
        self.assertEqual(result.status, "completed")
        expected = {"nested": {"value": 1}}
        self.assertEqual(queue.get(created.task_id).payload, expected)
        self.assertEqual(TaskQueue(self.state).get(created.task_id).payload, expected)

    def test_rejects_bad_arguments(self):
        queue = TaskQueue(self.state)
        with self.assertRaises(ValueError):
            queue.submit("", {})
        with self.assertRaises(ValueError):
            queue.submit("ok", [])

    def test_rejects_non_json_payload_before_queue_mutation(self):
        queue = TaskQueue(self.state)
        existing = queue.submit("ok", {"value": 1})
        original_bytes = self.state.read_bytes()
        original_ids = set(queue._tasks)

        for payload in ({"bad": object()}, {"not_finite": float("nan")}):
            with self.subTest(payload_type=type(next(iter(payload.values()))).__name__):
                with self.assertRaisesRegex(ValueError, "JSON-compatible"):
                    queue.submit("ok", payload)
                self.assertEqual(set(queue._tasks), original_ids)
                self.assertEqual(self.state.read_bytes(), original_bytes)

        self.assertEqual(queue.get(existing.task_id).payload, {"value": 1})

    def test_submit_rolls_back_memory_when_save_fails(self):
        queue = TaskQueue(self.state)
        existing = queue.submit("ok", {"value": 1})
        original_bytes = self.state.read_bytes()
        original_ids = set(queue._tasks)

        with patch.object(queue, "_save", side_effect=OSError("injected save failure")):
            with self.assertRaisesRegex(OSError, "injected save failure"):
                queue.submit("ok", {"value": 2})

        self.assertEqual(set(queue._tasks), original_ids)
        self.assertEqual(self.state.read_bytes(), original_bytes)
        self.assertEqual(queue.get(existing.task_id).payload, {"value": 1})


    def test_nested_submit_from_handler_is_reentrant_and_persists_both_tasks(self):
        repo_root = Path(__file__).resolve().parents[1]
        child_code = (
            "import sys\n"
            "from emberlane import TaskQueue\n"
            "queue = TaskQueue(sys.argv[1])\n"
            "parent = queue.submit('parent', {})\n"
            "def handler(payload):\n"
            "    child = queue.submit('child', {'value': 7})\n"
            "    return {'ok': True, 'child_id': child.task_id}\n"
            "result = queue.run_one({'parent': handler})\n"
            "assert result.status == 'completed', result\n"
            "restored = TaskQueue(sys.argv[1])\n"
            "assert restored.get(parent.task_id).status == 'completed'\n"
            "child_id = result.result['child_id']\n"
            "assert restored.get(child_id).status == 'pending'\n"
            "print('PASS', flush=True)\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", child_code, str(self.state)],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
