import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from emberlane import TaskQueue


_CHILD_CODE = r"""
import json
import sys
import time
from pathlib import Path
from emberlane import TaskQueue

state, gate, ready, mode, key, value = sys.argv[1:]
queue = TaskQueue(state)
Path(ready).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 10
while not Path(gate).exists():
    if time.monotonic() > deadline:
        raise SystemExit("barrier timeout")
    time.sleep(0.005)

if mode == "submit":
    task = queue.submit("echo", {"value": value}, idempotency_key=key or None)
    print(task.task_id)
elif mode == "run":
    def effect(payload):
        time.sleep(0.15)
        with Path(payload["marker"]).open("a", encoding="utf-8") as stream:
            stream.write("ran\n")
        return {"ok": True}
    task = queue.run_one({"effect": effect})
    print("none" if task is None else task.task_id)
elif mode == "prune":
    print(json.dumps(queue.prune_terminal(keep_terminal=0)))
else:
    raise SystemExit("unknown mode")
"""


class TaskQueueMultiprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state" / "queue.json"
        self.repo_root = Path(__file__).resolve().parents[1]

    def _run_together(self, specs):
        gate = self.root / "GO"
        processes = []
        ready_paths = []
        for index, (mode, key, value) in enumerate(specs):
            ready = self.root / f"ready-{index}"
            ready_paths.append(ready)
            process = subprocess.Popen(
                [
                    sys.executable, "-c", _CHILD_CODE, str(self.state),
                    str(gate), str(ready), mode, key, value,
                ],
                cwd=self.repo_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )
            processes.append(process)

        deadline = time.monotonic() + 15
        while not all(path.exists() for path in ready_paths):
            if time.monotonic() > deadline:
                gate.touch()
                for process in processes:
                    process.kill()
                self.fail("child processes did not reach the start barrier")
            time.sleep(0.01)

        gate.touch()
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stderr)
            outputs.append(stdout.strip())
        return outputs

    def test_concurrent_same_idempotency_key_creates_one_task(self):
        outputs = self._run_together([
            ("submit", "same-source-comment", "same-payload")
            for _ in range(8)
        ])

        self.assertEqual(len(set(outputs)), 1)
        tasks = TaskQueue(self.state).list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].idempotency_key, "same-source-comment")
        self.assertEqual(tasks[0].payload, {"value": "same-payload"})

    def test_concurrent_distinct_submits_are_not_lost(self):
        outputs = self._run_together([
            ("submit", f"source-{index}", f"value-{index}")
            for index in range(12)
        ])

        self.assertEqual(len(set(outputs)), 12)
        tasks = TaskQueue(self.state).list_tasks()
        self.assertEqual(len(tasks), 12)
        self.assertEqual({task.idempotency_key for task in tasks}, {
            f"source-{index}" for index in range(12)
        })
        self.assertEqual(len(json.loads(self.state.read_text(encoding="utf-8"))), 12)

    def test_concurrent_run_one_executes_one_task_only_once_concurrently(self):
        marker = self.root / "effects.txt"
        queue = TaskQueue(self.state)
        task = queue.submit("effect", {"marker": str(marker)})

        outputs = self._run_together([
            ("run", "", "unused"),
            ("run", "", "unused"),
        ])

        self.assertEqual(sorted(outputs), sorted([task.task_id, "none"]))
        self.assertEqual(marker.read_text(encoding="utf-8"), "ran\n")
        restored = TaskQueue(self.state).get(task.task_id)
        self.assertEqual(restored.status, "completed")
        self.assertEqual(restored.attempts, 1)

    def test_process_kill_recovers_running_task_below_retry_limit(self):
        queue = TaskQueue(self.state, max_attempts=2)
        task = queue.submit("kill", {"marker": "must-not-complete"})
        code = (
            "import os, sys\n"
            "from emberlane import TaskQueue\n"
            "queue = TaskQueue(sys.argv[1], max_attempts=int(sys.argv[2]))\n"
            "queue.run_one({'kill': lambda payload: os._exit(77)})\n"
        )
        child = subprocess.run(
            [sys.executable, "-c", code, str(self.state), "2"],
            cwd=self.repo_root, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5, check=False, shell=False,
        )
        self.assertEqual(child.returncode, 77, child.stderr)
        recovered = TaskQueue(self.state, max_attempts=2).get(task.task_id)
        self.assertEqual(recovered.status, "pending")
        self.assertEqual(recovered.attempts, 1)
        self.assertIn("may be retried", recovered.last_error)

    def test_process_kill_at_retry_limit_fails_closed(self):
        queue = TaskQueue(self.state, max_attempts=1)
        task = queue.submit("kill", {"marker": "side-effect-uncertain"})
        code = (
            "import os, sys\n"
            "from emberlane import TaskQueue\n"
            "queue = TaskQueue(sys.argv[1], max_attempts=int(sys.argv[2]))\n"
            "queue.run_one({'kill': lambda payload: os._exit(77)})\n"
        )
        child = subprocess.run(
            [sys.executable, "-c", code, str(self.state), "1"],
            cwd=self.repo_root, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5, check=False, shell=False,
        )
        self.assertEqual(child.returncode, 77, child.stderr)
        recovered = TaskQueue(self.state, max_attempts=1).get(task.task_id)
        self.assertEqual(recovered.status, "failed")
        self.assertEqual(recovered.attempts, 1)
        self.assertIn("manual recovery required", recovered.last_error)

    def test_prune_racing_with_submits_preserves_all_new_pending_tasks(self):
        queue = TaskQueue(self.state)
        for index in range(4):
            queue.submit("old", {"index": index}, idempotency_key=f"old-{index}")
        stored = queue.list_tasks()
        for index, task in enumerate(stored):
            queue._tasks[task.task_id].status = "completed"
            queue._tasks[task.task_id].updated_at = float(index + 1)
        queue._save()

        specs = [("prune", "", "unused")] + [
            ("submit", f"new-{index}", f"new-value-{index}")
            for index in range(10)
        ]
        self._run_together(specs)

        final_queue = TaskQueue(self.state)
        tasks = final_queue.list_tasks()
        self.assertEqual(len(tasks), 10)
        self.assertTrue(all(task.status == "pending" for task in tasks))
        self.assertEqual({task.idempotency_key for task in tasks}, {
            f"new-{index}" for index in range(10)
        })
        self.assertIsInstance(json.loads(self.state.read_text(encoding="utf-8")), list)


if __name__ == "__main__":
    unittest.main()
