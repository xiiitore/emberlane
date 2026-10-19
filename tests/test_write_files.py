"""Tests for validated multi-file coding tasks."""
import tempfile
import unittest
from pathlib import Path

from emberlane.worker import LocalWorker


class WriteFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worker = LocalWorker(self.root)

    def test_writes_multiple_files(self):
        task = self.worker.submit("write_files", {"files": [
            {"path": "src/one.py", "content": "VALUE = 1\n"},
            {"path": "tests/two.py", "content": "VALUE = 2\n"},
        ]})
        result = self.worker.run_one()
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["count"], 2)
        self.assertFalse(result.result["batch_atomic"])
        self.assertEqual((self.root / "src/one.py").read_text(), "VALUE = 1\n")
        self.assertEqual((self.root / "tests/two.py").read_text(), "VALUE = 2\n")

    def test_duplicate_paths_rejected_before_queueing(self):
        with self.assertRaisesRegex(ValueError, "duplicate path"):
            self.worker.submit("write_files", {"files": [
                {"path": "same.py", "content": "A = 1\n"},
                {"path": "same.py", "content": "A = 2\n"},
            ]})
        self.assertFalse((self.root / "same.py").exists())

    def test_invalid_entry_rejected_before_queueing(self):
        with self.assertRaisesRegex(ValueError, "string content"):
            self.worker.submit("write_files", {"files": [
                {"path": "valid.py", "content": "A = 1\n"},
                {"path": "invalid.py", "content": 42},
            ]})
        self.assertFalse((self.root / "valid.py").exists())

    def test_oversized_file_rejected_before_queueing(self):
        worker = LocalWorker(self.root, max_file_bytes=4)
        with self.assertRaisesRegex(ValueError, "configured size limit"):
            worker.submit("write_files", {"files": [
                {"path": "too_large.py", "content": "12345"},
            ]})
        self.assertEqual(worker.queue.list_tasks(), [])
        self.assertFalse((self.root / "too_large.py").exists())

    def test_invalid_later_target_does_not_create_earlier_directories(self):
        (self.root / "not_a_directory").write_text("file")
        with self.assertRaisesRegex(ValueError, "parent path is not a directory"):
            self.worker.workspace.validate_write_path("not_a_directory/child.py")
        self.assertFalse((self.root / "would_create").exists())

    def test_protected_paths_rejected(self):
        with self.assertRaisesRegex(ValueError, "protected paths"):
            self.worker.submit("write_files", {"files": [
                {"path": ".env", "content": "SECRET=bad\n"},
            ]})


if __name__ == "__main__":
    unittest.main()
