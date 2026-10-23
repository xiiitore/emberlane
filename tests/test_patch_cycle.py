import subprocess
import tempfile
import unittest
from pathlib import Path

from emberlane.patch_cycle import PatchCycleError, validate_patch_in_worktree, validate_patch_paths


class DisposablePatchCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "emberlane-test@example.invalid")
        self.git("config", "user.name", "Emberlane Tests")
        (self.root / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_ok.py").write_text(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_ok(self): self.assertEqual(1 + 1, 2)\n",
            encoding="utf-8",
        )
        self.git("add", "example.py", "tests/test_ok.py")
        self.git("commit", "-qm", "baseline")

    def git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
            shell=False,
        )

    def patch(self):
        return (
            "diff --git a/example.py b/example.py\n"
            "--- a/example.py\n"
            "+++ b/example.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
        )

    def test_validates_patch_in_disposable_worktree_without_touching_original(self):
        before = self.git("rev-parse", "HEAD").stdout.strip()
        result = validate_patch_in_worktree(self.root, self.patch())
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "validated")
        self.assertIsNone(result["passed"])
        self.assertFalse(result["tests_run"])
        self.assertTrue(result["worktree_discarded"])
        self.assertFalse(result["original_worktree_modified"])
        self.assertEqual(result["base_sha"], before)
        self.assertIn("example.py", result["touched_paths"])
        self.assertEqual((self.root / "example.py").read_text(), "VALUE = 1\n")
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        self.assertEqual(self.git("worktree", "list", "--porcelain").stdout.count("worktree "), 1)

    def test_optional_tests_run_in_disposable_worktree(self):
        result = validate_patch_in_worktree(self.root, self.patch(), run_tests=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["passed"])
        self.assertTrue(result["tests_run"])
        self.assertEqual(result["test_returncode"], 0)
        self.assertIn("Ran 1 test", result["test_output"])
        self.assertEqual((self.root / "example.py").read_text(), "VALUE = 1\n")

    def test_test_output_is_bounded_at_capture_boundary(self):
        output_test = self.root / "tests" / "test_output_volume.py"
        output_test.write_text(
            "import unittest\n"
            "class OutputVolume(unittest.TestCase):\n"
            "    def test_large_output(self): print('x' * 200000)\n",
            encoding="utf-8",
        )
        self.git("add", "tests/test_output_volume.py")
        self.git("commit", "-qm", "add output-volume fixture")
        result = validate_patch_in_worktree(self.root, self.patch(), run_tests=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["test_output_truncated"])
        self.assertLessEqual(len(result["test_output"]), 20_000)
        self.assertIn("Ran 2 tests", result["test_output"])
        self.assertEqual((self.root / "example.py").read_text(), "VALUE = 1\n")

    def test_test_timeout_cleans_disposable_worktree(self):
        timeout_test = self.root / "tests" / "test_timeout.py"
        timeout_test.write_text(
            "import time, unittest\n"
            "class TimeoutCase(unittest.TestCase):\n"
            "    def test_slow(self): time.sleep(10)\n",
            encoding="utf-8",
        )
        self.git("add", "tests/test_timeout.py")
        self.git("commit", "-qm", "add timeout fixture")
        with self.assertRaisesRegex(PatchCycleError, "exceeded 1-second timeout"):
            validate_patch_in_worktree(self.root, self.patch(), run_tests=True, test_timeout=1)
        self.assertEqual((self.root / "example.py").read_text(), "VALUE = 1\n")
        self.assertEqual(self.git("worktree", "list", "--porcelain").stdout.count("worktree "), 1)

    def test_rejects_protected_and_traversal_paths(self):
        for path in (".env", ".git/config", ".emberlane/queue.json", "../outside.py", "src/./outside.py"):
            with self.subTest(path=path):
                patch = (
                    f"diff --git a/{path} b/{path}\n"
                    f"--- a/{path}\n+++ b/{path}\n"
                    "@@ -1 +1 @@\n-old\n+new\n"
                )
                with self.assertRaises(PatchCycleError):
                    validate_patch_paths(patch)

    def test_rejects_file_header_path_hidden_by_safe_diff_header(self):
        patch = (
            "diff --git a/safe.py b/safe.py\n"
            "--- a/.git/config\n"
            "+++ b/.git/config\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        with self.assertRaises(PatchCycleError):
            validate_patch_paths(patch)

    def test_refuses_dirty_original_worktree(self):
        (self.root / "example.py").write_text("LOCAL CHANGE\n", encoding="utf-8")
        with self.assertRaisesRegex(PatchCycleError, "worktree is dirty"):
            validate_patch_in_worktree(self.root, self.patch())
        self.assertEqual((self.root / "example.py").read_text(), "LOCAL CHANGE\n")

    def test_rejects_symlinked_patch_target(self):
        (self.root / "link.py").symlink_to("example.py")
        self.git("add", "link.py")
        self.git("commit", "-qm", "add symlink")
        patch = (
            "diff --git a/link.py b/link.py\n"
            "--- a/link.py\n"
            "+++ b/link.py\n"
            "@@ -1 +1 @@\n"
            "-example.py\n"
            "+changed.py\n"
        )
        with self.assertRaisesRegex(PatchCycleError, "symlink"):
            validate_patch_in_worktree(self.root, patch)
        self.assertTrue((self.root / "link.py").is_symlink())
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_rejects_boolean_test_timeout(self):
        with self.assertRaisesRegex(PatchCycleError, "integer"):
            validate_patch_in_worktree(self.root, self.patch(), test_timeout=True)

    def test_rejects_empty_or_oversized_patch(self):
        with self.assertRaises(PatchCycleError):
            validate_patch_paths("")
        with self.assertRaisesRegex(PatchCycleError, "exceeds"):
            validate_patch_paths(self.patch() + ("x" * 256_000))


if __name__ == "__main__":
    unittest.main()
