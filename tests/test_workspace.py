import tempfile
import unittest
from pathlib import Path

from emberlane import Workspace, WorkspaceError


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.ws = Workspace(self.root, max_file_bytes=16)

    def test_write_read_and_list(self):
        self.ws.write_text("src/main.py", "print('ok')\n")
        self.assertEqual(self.ws.read_text("src/main.py"), "print('ok')\n")
        self.assertEqual(self.ws.list_files(), ["src/main.py"])

    def test_rejects_parent_traversal(self):
        with self.assertRaises(WorkspaceError):
            self.ws.write_text("../escape.txt", "no")
        with self.assertRaises(WorkspaceError):
            self.ws.read_text("../escape.txt")

    def test_rejects_absolute_path(self):
        with self.assertRaises(WorkspaceError):
            self.ws.read_text(str(self.root / "secret"))

    def test_enforces_file_size_limit(self):
        with self.assertRaises(WorkspaceError):
            self.ws.write_text("large.txt", "x" * 17)
        self.root.joinpath("large.txt").write_text("x" * 17)
        with self.assertRaises(WorkspaceError):
            self.ws.read_text("large.txt")

    def test_list_excludes_protected_runtime_and_git_paths(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("private")
        (self.root / ".emberlane").mkdir()
        (self.root / ".emberlane" / "queue.json").write_text("{}")
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "module.pyc").write_bytes(b"private")
        (self.root / ".env").write_text("SECRET=value")
        (self.root / "visible.py").write_text("VALUE=1")
        self.assertEqual(self.ws.list_files(), ["visible.py"])

    def test_rejects_symlink(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("private")
        link = self.root / "linked.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this platform")
        with self.assertRaises(WorkspaceError):
            self.ws.read_text("linked.txt")
        self.assertNotIn("linked.txt", self.ws.list_files())

    def test_atomic_write_replaces_existing_file(self):
        self.ws.write_text("result.txt", "old")
        self.ws.write_text("result.txt", "new")
        self.assertEqual(self.ws.read_text("result.txt"), "new")


if __name__ == "__main__":
    unittest.main()
