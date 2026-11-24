"""Hermes — the agents that speak for MIST outside this machine (Telegram and friends).

    GET /api/hermes?limit=6    gateway state per platform, the Hermes profiles and their
                               models, and the latest Telegram conversations (what was said,
                               not tool internals)

Read-only: the gateway's state file and its session store are opened `mode=ro`; nothing here
sends a message or touches the gateway. Loopback plus the inferN app's origins only (serve.py).
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3

HERMES = pathlib.Path.home() / ".hermes"


def _model_of(config: pathlib.Path) -> dict:
    """model.default / model.provider from a Hermes config.yaml, without a YAML dependency."""
    try:
        text = config.read_text(errors="replace")
    except OSError:
        return {}
    m = re.search(r"^model:\s*\n((?:[ \t]+.*\n)+)", text, re.M)
    out = {}
    for key in ("default", "provider"):
        k = re.search(r"^\s+%s:\s*(\S+)" % key, m.group(1), re.M) if m else None
        if k:
            out[key] = k.group(1).strip("'\"")
    return out


def _profiles() -> list:
    rows = [{"profile": "default", "persona": "MIST", **_model_of(HERMES / "config.yaml")}]
    for p in sorted((HERMES / "profiles").glob("*")):
        if p.is_dir():
            rows.append({"profile": p.name, **_model_of(p / "config.yaml")})
    return rows


def _gateway() -> dict:
    try:
        state = json.loads((HERMES / "gateway_state.json").read_text())
    except (OSError, ValueError):
        return {"state": "unknown", "platforms": {}}
    return {"state": state.get("gateway_state"), "updated_at": state.get("updated_at"),
            "version": state.get("code_version"), "active_agents": state.get("active_agents"),
            "platforms": {k: {"state": v.get("state"), "error": v.get("error_message"),
                              "updated_at": v.get("updated_at")}
                          for k, v in (state.get("platforms") or {}).items()}}


def _conversations(limit: int) -> list:
    db = HERMES / "state.db"
    if not db.is_file():
        return []
    conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        sessions = conn.execute(
            "SELECT id, source, model, title, started_at, ended_at, message_count, input_tokens, output_tokens "
            "FROM sessions WHERE source='telegram' ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for s in sessions:
            msgs = conn.execute(
                "SELECT role, content, timestamp FROM messages WHERE session_id=? AND role IN ('user','assistant') "
                "AND content IS NOT NULL AND TRIM(content)!='' AND active=1 ORDER BY timestamp DESC LIMIT 30",
                (s["id"],)).fetchall()
            last = conn.execute("SELECT MAX(timestamp) FROM messages WHERE session_id=?", (s["id"],)).fetchone()[0]
            out.append({**dict(s), "last_message_at": last,
                        "messages": [{"role": m["role"], "text": m["content"][:1500], "ts": m["timestamp"]}
                                     for m in reversed(msgs)]})
        return sorted(out, key=lambda s: -(s["last_message_at"] or s["started_at"] or 0))
    finally:
        conn.close()


def _hermes(match, query, body):
    try:
        limit = max(1, min(20, int((query.get("limit") or [6])[0])))
    except ValueError:
        limit = 6
    try:
        conversations = _conversations(limit)
        error = None
    except sqlite3.Error as exc:
        conversations, error = [], "session store unreadable: %s" % exc
    return 200, {"gateway": _gateway(), "profiles": _profiles(), "telegram": conversations, "error": error}


ROUTES = [("GET", re.compile(r"^/api/hermes$"), _hermes)]
