"""Cross-process regression tests for the file-backed task queue."""
from __future__ import annotations

import json
import multiprocessing
import os
import time
import unittest
from pathlib import Path

from emberlane import TaskQueue


def _submit_worker(state_path, key, payload, ready, start, output):
    queue = TaskQueue(state_path)
    ready.put("ready")
    if not start.wait(10):
        output.put({"error": "start timeout"})
        return
    try:
        task = queue.submit("write_file", payload, idempotency_key=key)
        output.put({"task_id": task.task_id})
    except Exception as exc:
        output.put({"error": type(exc).__name__ + ": " + str(exc)})


def _run_worker(state_path, task_id, effect_path, ready, start, output):
    queue = TaskQueue(state_path)
    ready.put("ready")
    if not start.wait(10):
        output.put({"error": "start timeout"})
        return

    def effect(payload):
        with open(effect_path, "a", encoding="utf-8") as stream:
            stream.write(str(os.getpid()) + "\\n")
            stream.flush()
            os.fsync(stream.fileno())
        time.sleep(0.15)
        return {"written": True}

    try:
        task = queue.run_task(task_id, {"effect": effect})
        output.put({"task_id": task.task_id if task else None,
                    "status": task.status if task else None})
    except Exception as exc:
        output.put({"error": type(exc).__name__ + ": " + str(exc)})


def _prune_worker(state_path, ready, start, output):
    queue = TaskQueue(state_path)
    ready.put("ready")
    if not start.wait(10):
        output.put({"error": "start timeout"})
        return
    try:
        output.put(queue.prune_terminal(keep_terminal=0))
    except Exception as exc:
        output.put({"error": type(exc).__name__ + ": " + str(exc)})


class TaskQueueMultiprocessTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "queue.json"
        self.ctx = multiprocessing.get_context("spawn")

    def _run_pair(self, target, args_pair):
        ready = self.ctx.Queue()
        output = self.ctx.Queue()
        start = self.ctx.Event()
        processes = [
            self.ctx.Process(target=target, args=(*args, ready, start, output))
            for args in args_pair
        ]
        for process in processes:
            process.start()
        try:
            self.assertEqual(ready.get(timeout=10), "ready")
            self.assertEqual(ready.get(timeout=10), "ready")
            start.set()
            results = [output.get(timeout=20), output.get(timeout=20)]
            for process in processes:
                process.join(timeout=20)
                self.assertFalse(process.is_alive(), "worker process did not exit")
                self.assertEqual(process.exitcode, 0)
            return results
        finally:
            start.set()
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            ready.close()
            output.close()

    def test_concurrent_distinct_submits_do_not_lose_tasks(self):
        payload_a = {"path": "a.txt", "content": "A"}
        payload_b = {"path": "b.txt", "content": "B"}
        results = self._run_pair(
            _submit_worker,
            [
                (str(self.state), "comment-a", payload_a),
                (str(self.state), "comment-b", payload_b),
            ],
        )
        self.assertTrue(all("task_id" in item for item in results), results)
        tasks = TaskQueue(self.state).list_tasks()
        self.assertEqual({task.idempotency_key for task in tasks}, {"comment-a", "comment-b"})
        self.assertEqual(len({task.task_id for task in tasks}), 2)
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8")).__len__(), 2)

    def test_concurrent_same_idempotency_key_returns_one_task(self):
        payload = {"path": "same.txt", "content": "same"}
        results = self._run_pair(
            _submit_worker,
            [
                (str(self.state), "same-comment", payload),
                (str(self.state), "same-comment", payload),
            ],
        )
        self.assertTrue(all("task_id" in item for item in results), results)
        self.assertEqual(results[0]["task_id"], results[1]["task_id"])
        tasks = TaskQueue(self.state).list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].idempotency_key, "same-comment")

    def test_two_processes_cannot_execute_the_same_task_concurrently(self):
        queue = TaskQueue(self.state)
        task = queue.submit("effect", {"value": 1}, idempotency_key="effect-1")
        effect_path = self.root / "effects.log"
        results = self._run_pair(
            _run_worker,
            [
                (str(self.state), task.task_id, str(effect_path)),
                (str(self.state), task.task_id, str(effect_path)),
            ],
        )
        self.assertTrue(all("error" not in item for item in results), results)
        self.assertEqual(sum(item["status"] == "completed" for item in results), 1)
        self.assertEqual(sum(item["status"] is None for item in results), 1)
        self.assertEqual(len(effect_path.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(TaskQueue(self.state).get(task.task_id).status, "completed")

    def test_prune_racing_with_submit_preserves_new_pending_task(self):
        queue = TaskQueue(self.state)
        old = queue.submit("old", {})
        old.status = "completed"
        old.updated_at = 1.0
        queue._save()
        payload = {"path": "new.txt", "content": "new"}
        # One child prunes while the other submits. The shared lock must serialize
        # both operations; a pending task must survive either ordering.
        ready = self.ctx.Queue()
        output = self.ctx.Queue()
        start = self.ctx.Event()
        prune = self.ctx.Process(target=_prune_worker, args=(str(self.state), ready, start, output))
        submit = self.ctx.Process(
            target=_submit_worker,
            args=(str(self.state), "new-comment", payload, ready, start, output),
        )
        prune.start()
        submit.start()
        try:
            self.assertEqual(ready.get(timeout=10), "ready")
            self.assertEqual(ready.get(timeout=10), "ready")
            start.set()
            first = output.get(timeout=20)
            second = output.get(timeout=20)
            for process in (prune, submit):
                process.join(timeout=20)
                self.assertFalse(process.is_alive(), "worker process did not exit")
                self.assertEqual(process.exitcode, 0)
            self.assertTrue(any(isinstance(item, dict) and "task_id" in item for item in (first, second)),
                            (first, second))
            tasks = TaskQueue(self.state).list_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].idempotency_key, "new-comment")
            self.assertEqual(tasks[0].status, "pending")
        finally:
            start.set()
            for process in (prune, submit):
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            ready.close()
            output.close()


if __name__ == "__main__":
    unittest.main()
