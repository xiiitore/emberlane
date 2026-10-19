"""Constrained file workspace for a local worker; not an OS security sandbox."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath


class WorkspaceError(ValueError):
    """Raised when an operation falls outside workspace policy."""


class Workspace:
    """Restrict worker file operations to one root directory.

    This protects against accidental path escape and common symlink traversal.
    It is not a security boundary against hostile processes running as the same
    OS user; use a separate OS account/container for that threat model.
    """

    def __init__(self, root: str | Path, max_file_bytes: int = 1_000_000):
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        supplied = Path(root)
        supplied.mkdir(parents=True, exist_ok=True)
        if supplied.is_symlink():
            raise WorkspaceError("workspace root must not be a symlink")
        self.root = supplied.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceError("workspace root must be a directory")
        self.max_file_bytes = max_file_bytes
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    def _resolve(self, relative: str | Path, *, for_write: bool = False) -> Path:
        raw = str(relative)
        if not raw or "\x00" in raw or "\\" in raw:
            raise WorkspaceError("invalid relative path")
        candidate_rel = PurePosixPath(raw)
        if candidate_rel.is_absolute() or any(p in ("", ".", "..") for p in candidate_rel.parts):
            raise WorkspaceError("path must be a clean relative path")
        if not candidate_rel.parts:
            raise WorkspaceError("path must name a file")
        current = self.root
        for part in candidate_rel.parts:
            current = current / part
            if current.is_symlink():
                raise WorkspaceError("symlinks are not allowed in workspace paths")
        parent = current.parent
        try:
            parent.resolve(strict=True).relative_to(self.root)
        except FileNotFoundError:
            if not for_write:
                raise WorkspaceError("parent directory does not exist")
            parent.mkdir(parents=True, exist_ok=True)
            try:
                parent.resolve(strict=True).relative_to(self.root)
            except (FileNotFoundError, ValueError):
                raise WorkspaceError("path escapes workspace root")
        except ValueError:
            raise WorkspaceError("path escapes workspace root")
        try:
            current.parent.resolve(strict=True).relative_to(self.root)
        except (FileNotFoundError, ValueError):
            raise WorkspaceError("path escapes workspace root")
        return current

    def list_files(self) -> list[str]:
        found: list[str] = []
        for base, dirs, files in os.walk(self.root, followlinks=False):
            base_path = Path(base)
            dirs[:] = sorted(d for d in dirs if not (base_path / d).is_symlink())
            for name in sorted(files):
                item = base_path / name
                if item.is_symlink():
                    continue
                if item.is_file():
                    found.append(item.relative_to(self.root).as_posix())
        return sorted(found)

    def read_text(self, relative: str | Path, encoding: str = "utf-8") -> str:
        path = self._resolve(relative)
        if not path.is_file():
            raise WorkspaceError("not a regular file")
        try:
            size = path.stat().st_size
            if size > self.max_file_bytes:
                raise WorkspaceError("file exceeds configured size limit")
            data = path.read_bytes()
        except OSError as exc:
            raise WorkspaceError(f"cannot read file: {exc}") from exc
        if len(data) > self.max_file_bytes:
            raise WorkspaceError("file exceeds configured size limit")
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as exc:
            raise WorkspaceError("file is not valid text in requested encoding") from exc

    def write_text(self, relative: str | Path, content: str, encoding: str = "utf-8") -> None:
        if not isinstance(content, str):
            raise WorkspaceError("content must be text")
        data = content.encode(encoding)
        if len(data) > self.max_file_bytes:
            raise WorkspaceError("content exceeds configured size limit")
        path = self._resolve(relative, for_write=True)
        if path.exists() and not path.is_file():
            raise WorkspaceError("target is not a regular file")
        fd, temporary = tempfile.mkstemp(prefix=".emberlane-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if path.is_symlink():
                raise WorkspaceError("symlinks are not allowed in workspace paths")
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
