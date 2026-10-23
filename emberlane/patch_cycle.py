"""Validate model-generated patches in a disposable Git worktree.

This is a review/test aid, not an OS security sandbox. Running tests is opt-in
because test code in an untrusted patch executes with the worker's permissions.
"""
from __future__ import annotations

import hashlib
import os
import signal
import threading
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

MAX_PATCH_BYTES = 256_000
MAX_RESULT_CHARS = 20_000
MAX_TEST_TIMEOUT = 300
PROTECTED_PARTS = {".git", ".emberlane", ".venv", "__pycache__"}
PROTECTED_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}


class PatchCycleError(ValueError):
    """Expected patch validation or worktree lifecycle failure."""


def _validate_repo_path(value: str) -> None:
    if not value or value.startswith(("/", "\\")) or "\\" in value:
        raise PatchCycleError("patch paths must be relative POSIX paths")
    raw_parts = value.split("/")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in raw_parts):
        raise PatchCycleError("patch path traversal is not allowed")
    if any(part in PROTECTED_PARTS or part in PROTECTED_NAMES for part in path.parts):
        raise PatchCycleError("patch modifies a protected path")
    if path.parts and (path.parts[0].endswith(":") or path.parts[0].startswith("~")):
        raise PatchCycleError("patch path failed relative-path validation")


def validate_patch_paths(patch: str) -> list[str]:
    """Validate Git diff and file headers, returning unique touched paths."""
    if not isinstance(patch, str) or not patch.strip():
        raise PatchCycleError("patch must be a non-empty string")
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise PatchCycleError(f"patch exceeds {MAX_PATCH_BYTES} bytes")

    paths: list[str] = []
    expected_old: str | None = None
    expected_new: str | None = None
    old_seen = False
    new_seen = False
    in_file_headers = False

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            header = line[len("diff --git "):]
            if not header.startswith("a/") or " b/" not in header:
                raise PatchCycleError("patch contains a malformed or unsupported diff header")
            left, right = header[2:].split(" b/", 1)
            if '"' in left or '"' in right:
                raise PatchCycleError("quoted/ambiguous patch paths are not supported")
            _validate_repo_path(left)
            _validate_repo_path(right)
            paths.extend((left, right))
            expected_old, expected_new = left, right
            old_seen = new_seen = False
            in_file_headers = True
            continue

        if in_file_headers and line.startswith("@@"):
            in_file_headers = False
            continue
        if in_file_headers and line == "GIT binary patch":
            in_file_headers = False
            continue

        if not in_file_headers:
            continue
        if line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            raise PatchCycleError("rename/copy metadata is not supported by the safe patch validator")
        if line.startswith(("new file mode 120000", "old mode 120000", "new mode 120000")):
            raise PatchCycleError("symbolic-link changes are not supported by the safe patch validator")
        if line.startswith("--- "):
            raw = line[4:].split("\t", 1)[0]
            if raw == "/dev/null":
                old_seen = True
                continue
            if not raw.startswith("a/") or '"' in raw:
                raise PatchCycleError("patch contains a malformed old-file header")
            value = raw[2:]
            _validate_repo_path(value)
            if expected_old != value:
                raise PatchCycleError("old-file header does not match diff path")
            old_seen = True
            paths.append(value)
        elif line.startswith("+++ "):
            raw = line[4:].split("\t", 1)[0]
            if raw == "/dev/null":
                new_seen = True
                continue
            if not raw.startswith("b/") or '"' in raw:
                raise PatchCycleError("patch contains a malformed new-file header")
            value = raw[2:]
            _validate_repo_path(value)
            if expected_new != value:
                raise PatchCycleError("new-file header does not match diff path")
            new_seen = True
            paths.append(value)

    if not paths:
        raise PatchCycleError("patch contains no supported git diff headers")
    return list(dict.fromkeys(paths))

def _run_git(args: list[str], *, cwd: Path, timeout: int = 15, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL if input_text is None else None,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PatchCycleError(f"git command timed out: git {args[0]}") from exc
    except OSError as exc:
        raise PatchCycleError(f"could not run git ({type(exc).__name__})") from exc



def _run_bounded_tests(checkout: Path, timeout: int) -> tuple[int, str, bool]:
    """Run the fixed unittest command with bounded in-memory output and timeout."""
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    try:
        process = subprocess.Popen(
            command,
            cwd=checkout,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            shell=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise PatchCycleError(f"could not start test runner ({type(exc).__name__})") from exc

    assert process.stdout is not None
    retained = bytearray()
    truncated = False

    def drain() -> None:
        nonlocal truncated
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            retained.extend(chunk)
            if len(retained) > MAX_RESULT_CHARS:
                truncated = True
                del retained[:-MAX_RESULT_CHARS]
        process.stdout.close()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.wait()
        reader.join(timeout=5)
        raise PatchCycleError(f"test command exceeded {timeout}-second timeout") from exc
    reader.join(timeout=5)
    if reader.is_alive():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        raise PatchCycleError("test output pipe did not close after child exit")
    return returncode, retained.decode("utf-8", errors="replace"), truncated


def validate_patch_in_worktree(
    root: str | Path,
    patch: str,
    *,
    run_tests: bool = False,
    test_timeout: int = 120,
) -> dict[str, Any]:
    """Check/apply a patch in a temporary worktree; never alter the original checkout."""
    repo = Path(root).resolve()
    if not repo.is_dir():
        raise PatchCycleError("repository root must be an existing directory")
    if not isinstance(run_tests, bool):
        raise PatchCycleError("run_tests must be a boolean")
    if (
        isinstance(test_timeout, bool)
        or not isinstance(test_timeout, int)
        or not 1 <= test_timeout <= MAX_TEST_TIMEOUT
    ):
        raise PatchCycleError(f"test_timeout must be an integer from 1 to {MAX_TEST_TIMEOUT}")
    touched_paths = validate_patch_paths(patch)

    status = _run_git(["status", "--porcelain", "--untracked-files=all"], cwd=repo)
    if status.returncode != 0:
        raise PatchCycleError("repository status check failed")
    # Emberlane's own queue/state files are runtime artifacts, not source changes.
    dirty_source_lines = [
        line for line in status.stdout.splitlines()
        if not line[3:].replace("\\", "/").startswith(".emberlane/")
    ]
    if dirty_source_lines:
        raise PatchCycleError("original worktree is dirty; refusing to validate against ambiguous state")
    root_result = _run_git(["rev-parse", "--show-toplevel"], cwd=repo)
    head_result = _run_git(["rev-parse", "HEAD"], cwd=repo)
    if root_result.returncode != 0 or head_result.returncode != 0:
        raise PatchCycleError("root must be a Git worktree with a valid HEAD")
    if Path(root_result.stdout.strip()).resolve() != repo:
        raise PatchCycleError("configured root must be the Git worktree root")
    base_sha = head_result.stdout.strip()
    patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()

    parent = Path(tempfile.mkdtemp(prefix="emberlane-patch-cycle-"))
    checkout = parent / "checkout"
    worktree_added = False
    try:
        add = _run_git(["worktree", "add", "--detach", str(checkout), base_sha], cwd=repo, timeout=60)
        if add.returncode != 0:
            raise PatchCycleError(f"could not create disposable worktree: {add.stdout[-2000:]}")
        worktree_added = True

        # Never let patch application traverse a symlink already present in the base tree.
        for touched in touched_paths:
            candidate = checkout
            for part in PurePosixPath(touched).parts:
                candidate = candidate / part
                if candidate.is_symlink():
                    raise PatchCycleError(f"patch target traverses a symlink: {touched}")

        check = _run_git(["apply", "--check"], cwd=checkout, input_text=patch)
        if check.returncode != 0:
            return {
                "ok": False, "passed": False, "stage": "patch_check",
                "error": check.stdout[-2000:], "base_sha": base_sha,
                "patch_sha256": patch_sha256, "touched_paths": touched_paths,
                "tests_run": False,
            }
        applied = _run_git(["apply"], cwd=checkout, input_text=patch)
        if applied.returncode != 0:
            return {
                "ok": False, "passed": False, "stage": "patch_apply",
                "error": applied.stdout[-2000:], "base_sha": base_sha,
                "patch_sha256": patch_sha256, "touched_paths": touched_paths,
                "tests_run": False,
            }
        whitespace = _run_git(["diff", "--check"], cwd=checkout)
        if whitespace.returncode != 0:
            return {
                "ok": False, "passed": False, "stage": "diff_check",
                "error": whitespace.stdout[-2000:], "base_sha": base_sha,
                "patch_sha256": patch_sha256, "touched_paths": touched_paths,
                "tests_run": False,
            }
        stat = _run_git(["diff", "--stat"], cwd=checkout)
        if stat.returncode != 0:
            raise PatchCycleError("could not inspect disposable-worktree diff")
        if not stat.stdout.strip():
            return {
                "ok": False, "passed": False, "stage": "no_changes",
                "error": "patch produced no changes in the disposable worktree",
                "base_sha": base_sha, "patch_sha256": patch_sha256,
                "touched_paths": touched_paths, "tests_run": False,
                "worktree_discarded": True, "original_worktree_modified": False,
            }

        result: dict[str, Any] = {
            "ok": True,
            "status": "validated",
            "passed": None,
            "stage": "patch_validated",
            "base_sha": base_sha,
            "patch_sha256": patch_sha256,
            "touched_paths": touched_paths,
            "diff_stat": stat.stdout[-MAX_RESULT_CHARS:],
            "tests_run": False,
            "worktree_discarded": True,
            "original_worktree_modified": False,
        }
        if run_tests:
            test_returncode, output, output_truncated = _run_bounded_tests(checkout, test_timeout)
            result.update({
                "ok": test_returncode == 0,
                "passed": test_returncode == 0,
                "stage": "tests_passed" if test_returncode == 0 else "tests_failed",
                "tests_run": True,
                "test_returncode": test_returncode,
                "test_output": output,
                "test_output_truncated": output_truncated,
            })
        return result
    except subprocess.TimeoutExpired:
        raise PatchCycleError(f"test command exceeded {test_timeout}-second timeout")
    finally:
        if worktree_added:
            _run_git(["worktree", "remove", "--force", str(checkout)], cwd=repo, timeout=30)
        shutil.rmtree(parent, ignore_errors=True)
