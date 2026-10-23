"""Regression tests for workspace path containment and symlink rejection."""
import tempfile
import unittest
from pathlib import Path

from emberlane.workspace import Workspace, WorkspaceError


class WorkspacePathSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / "workspace"
        self.root.mkdir()
        self.outside = base / "outside.txt"
        self.outside.write_text("unchanged", encoding="utf-8")
        self.workspace = Workspace(self.root)

    def test_rejects_parent_traversal_for_read_and_write(self):
        with self.assertRaises(WorkspaceError):
            self.workspace.read_text("../outside.txt")
        with self.assertRaises(WorkspaceError):
            self.workspace.write_text("../outside.txt", "overwritten")
        self.assertEqual(self.outside.read_text(encoding="utf-8"), "unchanged")

    def test_rejects_absolute_paths_for_read_and_write(self):
        with self.assertRaises(WorkspaceError):
            self.workspace.read_text(str(self.outside))
        with self.assertRaises(WorkspaceError):
            self.workspace.write_text(str(self.outside), "overwritten")
        self.assertEqual(self.outside.read_text(encoding="utf-8"), "unchanged")

    def test_rejects_symlink_to_outside_for_read_and_write(self):
        link = self.root / "escape.txt"
        try:
            link.symlink_to(self.outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(WorkspaceError):
            self.workspace.read_text("escape.txt")
        with self.assertRaises(WorkspaceError):
            self.workspace.write_text("escape.txt", "overwritten")
        self.assertEqual(self.outside.read_text(encoding="utf-8"), "unchanged")

    def test_rejects_symlinked_parent_directory(self):
        outside_dir = Path(self.temp.name) / "outside-dir"
        outside_dir.mkdir()
        original = outside_dir / "original.txt"
        original.write_text("unchanged", encoding="utf-8")
        try:
            (self.root / "linked").symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(WorkspaceError):
            self.workspace.read_text("linked/original.txt")
        with self.assertRaises(WorkspaceError):
            self.workspace.write_text("linked/new.txt", "escape")
        self.assertEqual(original.read_text(encoding="utf-8"), "unchanged")
        self.assertFalse((outside_dir / "new.txt").exists())


if __name__ == "__main__":
    unittest.main()
