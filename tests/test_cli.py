import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from emberlane.worker import LocalWorker, main


class GoalPlannerCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def goal_payload(self):
        return {
            "goal_id": "cli-goal",
            "steps": [
                {"id": "inspect", "kind": "diagnostics", "payload": {}}
            ],
            "max_steps_per_cycle": 1,
            "max_cycles": 3,
        }

    def test_cli_accepts_and_persists_plan_goal(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([
                "--root", str(self.root), "submit", "plan_goal",
                "--payload", json.dumps(self.goal_payload()),
            ])
        self.assertEqual(code, 0)
        emitted = json.loads(stdout.getvalue())
        self.assertEqual(emitted["kind"], "plan_goal")
        self.assertEqual(emitted["status"], "pending")
        task = LocalWorker(self.root).queue.get(emitted["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task.payload["goal_id"], "cli-goal")

    def test_cli_run_one_advances_submitted_goal(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--root", str(self.root), "submit", "plan_goal",
                "--payload", json.dumps(self.goal_payload()),
            ]), 0)
            self.assertEqual(main(["--root", str(self.root), "run-one"]), 0)

        tasks = LocalWorker(self.root).queue.list_tasks()
        self.assertEqual(tasks[0].kind, "plan_goal")
        self.assertEqual(tasks[0].status, "completed")
        self.assertTrue(any(t.kind == "diagnostics" and t.status == "pending" for t in tasks))
        self.assertTrue(any(t.kind == "plan_goal" and t.status == "pending" for t in tasks[1:]))

    def test_cli_accepts_queue_prune_task(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([
                "--root", str(self.root), "submit", "queue_prune",
                "--payload", json.dumps({"keep_terminal": 5}),
            ])
        self.assertEqual(code, 0)
        emitted = json.loads(stdout.getvalue())
        self.assertEqual(emitted["kind"], "queue_prune")
        self.assertEqual(emitted["status"], "pending")

    def test_invalid_goal_is_failed_by_planner_not_executed_as_shell(self):
        payload = {"goal_id": "invalid", "steps": [
            {"id": "bad", "kind": "shell", "payload": {"command": "id"}}
        ]}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--root", str(self.root), "submit", "plan_goal",
                "--payload", json.dumps(payload),
            ]), 0)
            result = 0
            for _ in range(3):
                result = main(["--root", str(self.root), "run-one"])
        self.assertEqual(result, 1)
        tasks = LocalWorker(self.root).queue.list_tasks()
        self.assertEqual(tasks[0].status, "failed")
        self.assertIn("not allowed", tasks[0].last_error)


    def test_cli_exposes_bounded_supervisor_and_audits_one_task(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main([
                "--root", str(self.root), "submit", "diagnostics",
                "--payload", "{}",
            ]), 0)
            code = main([
                "--root", str(self.root), "supervise",
                "--max-tasks", "1", "--max-failures", "2", "--max-seconds", "30",
            ])
        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue().splitlines()[-1])
        self.assertEqual(report["status"], "task_limit")
        self.assertEqual(report["processed"], 1)
        self.assertTrue((self.root / ".emberlane" / "supervisor.jsonl").is_file())

    def test_cli_allows_guarded_git_publish_task_kinds(self):
        for kind, payload in (
            ("git_commit", {"expected_branch": "feature", "paths": ["src/a.py"], "message": "fix"}),
            ("git_push", {"expected_branch": "feature"}),
        ):
            with self.subTest(kind=kind):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = main([
                        "--root", str(self.root), "submit", kind,
                        "--payload", json.dumps(payload),
                    ])
                self.assertEqual(code, 0)
                emitted = json.loads(stdout.getvalue())
                self.assertEqual(emitted["kind"], kind)
                self.assertEqual(emitted["status"], "pending")


if __name__ == "__main__":
    unittest.main()
