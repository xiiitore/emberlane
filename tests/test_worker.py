import tempfile
import unittest
from pathlib import Path

from emberlane.worker import LocalWorker


class LocalWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tests").mkdir()
        self.worker = LocalWorker(self.root)

    def test_write_read_and_result_persists(self):
        task = self.worker.submit("write_file", {
            "path": "src/example.py", "content": "VALUE = 42\n"
        })
        result = self.worker.run_one()
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["bytes_written"], len("VALUE = 42\n".encode()))
        restored = LocalWorker(self.root).queue.get(task.task_id)
        self.assertEqual(restored.result, result.result)

        read = self.worker.submit("read_file", {"path": "src/example.py"})
        result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["content"], "VALUE = 42\n")

    def test_blocks_git_metadata(self):
        task = self.worker.submit("write_file", {
            "path": ".git/config", "content": "overwrite"
        })
        result = self.worker.run_one()
        self.assertEqual(result.status, "failed")
        self.assertIn("protected paths", result.last_error)

    def test_unknown_task_kind_rejected_before_enqueue(self):
        with self.assertRaises(ValueError):
            self.worker.submit("run_shell", {"command": "id"})

    def test_run_tests_uses_fixed_command(self):
        (self.root / "tests" / "test_ok.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n"
            " def test_ok(self): self.assertEqual(1 + 1, 2)\n"
        )
        task = self.worker.submit("run_tests", {})
        result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.result["passed"])
        self.assertEqual(result.result["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
