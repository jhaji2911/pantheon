"""MIST acts — the god's write path.

The rest of the console is read-only by charter: `bridge.py` opens the colony's
SQLite `mode=ro` and never writes. This module is the deliberate, gated exception:
MIST's operating commands — the exact same `colony` CLI surface — re-exposed as
explicit POSTs. Each action runs the real `colony` CLI in a subprocess, so the
console process itself never imports the colony's write path and a broken colony
action cannot take the console down.

GET  /api/mist        — the god's panel: pending petitions, standing directive,
                        reach status, reviews awaiting verdict, the roster, and
                        the available actions.
POST /api/mist/act    — {action, ...fields}: run one operating command.

Loopback-only (the console binds 127.0.0.1), same trust boundary as the `colony`
CLI. Every action is an explicit POST; nothing here fires without a request.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

from bridge import world_view

COLONY_REPO = pathlib.Path.home() / "Code" / "colony"

# action name -> (argv words, required field names). {field} placeholders are
# filled from the request body; empty optional fields are dropped.
ACTIONS = {
    "petition-approve": (["petition", "approve", "{id}"], ["id"]),
    "petition-reject":  (["petition", "reject", "{id}"], ["id"]),
    "note":             (["note", "{text}"], ["text"]),
    "note-clear":       (["note", "--clear"], []),
    "grant":            (["grant", "{agent}", "{credits}", "{reason}"], ["agent", "credits"]),
    "spawn":            (["spawn", "{agent}"], ["agent"]),
    "reach-on":         (["reach", "on"], []),
    "reach-off":        (["reach", "off"], []),
    "reach-status":     (["reach", "status"], []),
    "judge-accept":     (["judge", "{task}", "accept"], ["task"]),
    "judge-reject":     (["judge", "{task}", "reject"], ["task"]),
    "dispatch":         (["dispatch", "{brief}"], ["brief"]),
}


def _argv(action: str, fields: dict) -> list:
    argv = []
    for word in ACTIONS[action][0]:
        m = re.search(r"\{(\w+)\}", word)
        if m:
            value = str(fields.get(m.group(1)) or "").strip()
            if value:
                argv.append(value)
        else:
            argv.append(word)
    return argv


def _run(action: str, fields: dict) -> dict:
    missing = [f for f in ACTIONS[action][1] if not str(fields.get(f) or "").strip()]
    if missing:
        return {"ok": False, "status": 400, "error": "missing: " + ", ".join(missing)}
    argv = _argv(action, fields)
    try:
        proc = subprocess.run([sys.executable, "-m", "colony"] + argv,
                              cwd=str(COLONY_REPO), capture_output=True,
                              text=True, timeout=300)
    except FileNotFoundError as exc:
        return {"ok": False, "status": 502, "error": "colony not runnable: %s" % exc}
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": 504, "error": "colony command timed out"}
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    data = None
    try:
        data = json.loads(stdout)
    except (ValueError, json.JSONDecodeError):
        data = None
    return {"ok": proc.returncode == 0, "code": proc.returncode,
            "stdout": stdout[-4000:], "stderr": stderr[-2000:], "data": data}


def _reach_status() -> bool | None:
    try:
        proc = subprocess.run([sys.executable, "-m", "colony", "reach", "status"],
                              cwd=str(COLONY_REPO), capture_output=True,
                              text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"hermes_reach:\s*(\S+)", proc.stdout or "")
    return m.group(1) == "GRANTED" if m else None


def _menu() -> dict:
    try:
        view = world_view()
    except Exception as exc:                                    # noqa: BLE001
        return {"error": "colony unreadable: %s: %s" % (type(exc).__name__, exc)}
    petitions = [p for p in view.get("petitions") or []
                 if p.get("status") in ("pending", "awaiting_mist")]
    reviews = [t for t in view.get("tasks") or [] if t.get("status") == "review"]
    return {
        "tick": view.get("tick"),
        "directive": view.get("directive") or "",
        "petitions": petitions,
        "reviews": reviews,
        "reach": _reach_status(),
        "roster": [{"name": a["name"], "tier": a["tier"], "domain": a["domain"],
                    "credits": a["credits"], "fitness": a["fitness"]}
                   for a in view.get("agents") or []],
        "actions": sorted(ACTIONS.keys()),
    }


def _mist(match, query, body):
    return 200, _menu()


def _act(match, query, body):
    body = body or {}
    action = (body.get("action") or "").strip()
    if action not in ACTIONS:
        return 400, {"error": "unknown action", "known": sorted(ACTIONS.keys())}
    result = _run(action, body)
    status = result.pop("status", (200 if result.get("ok") else 502))
    try:
        result["menu"] = _menu()
    except Exception:                                           # noqa: BLE001
        pass
    return status, result


ROUTES = [
    ("GET", re.compile(r"^/api/mist$"), _mist),
    ("POST", re.compile(r"^/api/mist/act$"), _act),
]
