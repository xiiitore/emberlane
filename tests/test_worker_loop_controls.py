import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import worker_loop


class WorkerLoopControlTests(unittest.TestCase):
    def test_stop_marker_takes_precedence_over_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".emberlane"
            state.mkdir()
            (state / "PAUSED").touch()
            (state / "STOP").touch()
            self.assertEqual(worker_loop.control_state(root), "stopped")

    def test_pause_marker_prevents_polling_until_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".emberlane"
            state.mkdir()
            (state / "PAUSED").touch()
            self.assertEqual(worker_loop.control_state(root), "paused")
            (state / "PAUSED").unlink()
            self.assertIsNone(worker_loop.control_state(root))

    def test_stop_marker_exits_before_mailbox_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / ".emberlane"
            state.mkdir()
            (state / "STOP").touch()
            log_path = state / "worker-loop.log"
            lock_path = state / "worker-loop.lock"

            with (
                patch.object(worker_loop, "ROOT", root),
                patch.object(worker_loop, "STATE_DIR", state),
                patch.object(worker_loop, "LOG_PATH", log_path),
                patch.object(worker_loop, "LOCK_PATH", lock_path),
                patch.object(worker_loop, "refresh_continuity_state"),
                patch.object(worker_loop, "log") as log,
                patch.object(worker_loop.subprocess, "run") as run,
                patch.object(worker_loop.signal, "signal"),
            ):
                self.assertEqual(worker_loop.main(), 0)

            run.assert_not_called()
            log.assert_any_call("stopped", reason=".emberlane/STOP")


if __name__ == "__main__":
    unittest.main()
