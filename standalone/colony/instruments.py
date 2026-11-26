"""Notebook reads for the mind view (the only instrument Pantheon calls)."""
from __future__ import annotations

import pathlib

from . import settings


def notebook_read(agent_name, relpath, limit=8000):
    rel = pathlib.PurePosixPath(str(relpath))
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("path must stay inside the CI's own notebook")
    base = settings.SANDBOX / "".join(ch for ch in agent_name if ch.isalnum() or ch in "-_")
    target = base / rel
    if not target.exists():
        return {"error": "no such note", "path": str(rel)}
    return {"path": str(rel), "text": target.read_text(errors="replace")[:limit]}
