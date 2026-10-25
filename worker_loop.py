#!/usr/bin/env python3
"""Supervised polling loop for the Emberlane GitHub issue mailbox.

Run from the repository root in Termux: python worker_loop.py
Stop cleanly with Ctrl-C. One process is enforced with an advisory file lock.
"""
from __future__ import annotations

import fcntl
import json
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = "xiiitore/emberlane"
ISSUE = 6
AUTHOR = "xiiitore"
POLL_SECONDS = 15
COMMAND_TIMEOUT_SECONDS = 180
ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / ".emberlane"
LOG_PATH = STATE_DIR / "worker-loop.log"
LOCK_PATH = STATE_DIR / "worker-loop.lock"
STOP_MARKER = ".emberlane/STOP"
PAUSE_MARKER = ".emberlane/PAUSED"
stop_requested = False


def control_state(root: Path = ROOT) -> str | None:
    """Return the control marker state; STOP takes precedence over PAUSED."""
    if (root / STOP_MARKER).exists():
        return "stopped"
    if (root / PAUSE_MARKER).exists():
        return "paused"
    return None


def refresh_continuity_state() -> None:
    try:
        from emberlane.session_state import refresh_session_state
        result = refresh_session_state(ROOT)
        if result.get("status") not in {"unchanged", "retry_deferred"}:
            log("session_state", **result)
    except Exception as exc:
        # State publishing must never stop the task mailbox loop.
        log("session_state_error", error_type=type(exc).__name__)


def log(event: str, **details: object) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {"time": datetime.now(timezone.utc).isoformat(), "event": event, **details},
        ensure_ascii=False,
        sort_keys=True,
    )
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def request_stop(_signum: int, _frame: object) -> None:
    global stop_requested
    stop_requested = True


def main() -> int:
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    with LOCK_PATH.open("w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Emberlane worker loop already appears to be running.", file=sys.stderr)
            return 2

        log("started", repo=REPO, issue=ISSUE, author=AUTHOR, poll_seconds=POLL_SECONDS)
        refresh_continuity_state()
        while not stop_requested:
            state = control_state(ROOT)
            if state == "stopped":
                log("stopped", reason=STOP_MARKER)
                break
            if state == "paused":
                log("paused", reason=PAUSE_MARKER)
                # Stay responsive to stop markers and signals without busy-spinning.
                deadline = time.monotonic() + POLL_SECONDS
                while not stop_requested and time.monotonic() < deadline:
                    if control_state(ROOT) != "paused":
                        break
                    time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
                continue

            started = time.monotonic()
            try:
                result = subprocess.run(
                    [
                        sys.executable, "-m", "emberlane", "--root", str(ROOT),
                        "mailbox-once", "--repo", REPO, "--issue", str(ISSUE),
                        "--author", AUTHOR,
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=COMMAND_TIMEOUT_SECONDS,
                    check=False,
                )
                stdout = result.stdout.strip()
                stderr = result.stderr.strip()
                try:
                    parsed = json.loads(stdout) if stdout else None
                except json.JSONDecodeError:
                    parsed = None
                log(
                    "poll_finished",
                    returncode=result.returncode,
                    result=parsed,
                    stdout=None if parsed is not None else stdout[-2000:],
                    stderr=stderr[-2000:] or None,
                )
                refresh_continuity_state()
            except subprocess.TimeoutExpired:
                log("poll_timeout", timeout_seconds=COMMAND_TIMEOUT_SECONDS)
            except Exception as exc:
                log("poll_error", error_type=type(exc).__name__, error=str(exc))

            remaining = max(0.0, POLL_SECONDS - (time.monotonic() - started))
            deadline = time.monotonic() + remaining
            while not stop_requested and time.monotonic() < deadline:
                time.sleep(min(0.5, deadline - time.monotonic()))

        if control_state(ROOT) != "stopped":
            log("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
