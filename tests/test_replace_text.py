"""Regression tests for exact, guarded text-edit tasks."""
import tempfile
import unittest
from pathlib import Path

from emberlane.worker import LocalWorker
from emberlane.workspace import WorkspaceError


class ReplaceTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worker = LocalWorker(self.root)

    def test_replaces_one_exact_occurrence_through_queue(self):
        target = self.root / "module.py"
        target.write_text("VALUE = 1\nOTHER = 2\n", encoding="utf-8")
        task = self.worker.submit("replace_text", {
            "path": "module.py",
            "old": "VALUE = 1",
            "new": "VALUE = 42",
        })
        result = self.worker.run_one()
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["replacements"], 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 42\nOTHER = 2\n")

    def test_replaces_multiple_occurrences_only_when_count_matches(self):
        target = self.root / "module.py"
        target.write_text("x = 1\ny = 1\n", encoding="utf-8")
        result = self.worker._replace_text({
            "path": "module.py",
            "old": "= 1",
            "new": "= 2",
            "expected_count": 2,
        })
        self.assertEqual(result["replacements"], 2)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 2\ny = 2\n")

    def test_mismatch_leaves_file_unchanged(self):
        target = self.root / "module.py"
        target.write_text("VALUE = 1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "file unchanged"):
            self.worker._replace_text({
                "path": "module.py",
                "old": "MISSING",
                "new": "VALUE = 2",
            })
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_oversized_result_leaves_file_unchanged(self):
        worker = LocalWorker(self.root, max_file_bytes=8)
        target = self.root / "module.py"
        target.write_text("A=1\n", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceError, "size limit"):
            worker._replace_text({
                "path": "module.py",
                "old": "A=1",
                "new": "VALUE = 12345",
            })
        self.assertEqual(target.read_text(encoding="utf-8"), "A=1\n")

    def test_rejects_protected_path_before_queueing(self):
        with self.assertRaisesRegex(WorkspaceError, "protected paths"):
            self.worker.submit("replace_text", {
                "path": ".env",
                "old": "SECRET=old",
                "new": "SECRET=new",
            })
        self.assertEqual(self.worker.queue.list_tasks(), [])

    def test_rejects_invalid_expected_count_before_queueing(self):
        for invalid in (0, -1, True, 1.5, 1001):
            with self.subTest(expected_count=invalid):
                with self.assertRaisesRegex(ValueError, "expected_count"):
                    self.worker.submit("replace_text", {
                        "path": "module.py",
                        "old": "x",
                        "new": "y",
                        "expected_count": invalid,
                    })
        self.assertEqual(self.worker.queue.list_tasks(), [])


if __name__ == "__main__":
    unittest.main()
