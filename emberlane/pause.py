"""Persistent pause/stop markers shared by the worker, planner and local backends."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

ControlState = Literal["paused", "stopped"]


def control_state(root: str | Path) -> ControlState | None:
    """Return the active control marker; STOP takes precedence over PAUSED."""
    marker_dir = Path(root) / ".emberlane"
    if (marker_dir / "STOP").exists():
        return "stopped"
    if (marker_dir / "PAUSED").exists():
        return "paused"
    return None
