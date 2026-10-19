"""Tests for metadata-only git diff reporting."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from emberlane.worker import LocalWorker


class GitDiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "emberlane-test@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Emberlane Test"], cwd=self.root, check=True)
        (self.root / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "example.py"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.root, check=True)
        (self.root / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.worker = LocalWorker(self.root)

    def test_reports_changed_file_and_stat_without_source_patch(self):
        task = self.worker.submit("git_diff", {})
        result = self.worker.run_one()
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["files"]["returncode"], 0)
        self.assertIn("example.py", result.result["files"]["output"])
        self.assertEqual(result.result["stat"]["returncode"], 0)
        self.assertIn("example.py", result.result["stat"]["output"])
        self.assertFalse(result.result["patch_included"])
        self.assertNotIn("patch", result.result)

    def test_path_filter_is_applied_to_metadata(self):
        (self.root / "other.py").write_text("VALUE = 3\n", encoding="utf-8")
        task = self.worker.submit("git_diff", {"path": "example.py"})
        result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertIn("example.py", result.result["files"]["output"])
        self.assertNotIn("other.py", result.result["files"]["output"])


if __name__ == "__main__":
    unittest.main()
