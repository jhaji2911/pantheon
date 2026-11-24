"""Assemblies: meetings, dinners and townhalls — the CIs in a room, on the record.

GET  /api/assemblies      — past assemblies (newest first)
GET  /api/assembly/<id>   — one assembly, whole transcript
POST /api/assembly        — convene one now: {kind, topic, cis[], rounds}
"""
from __future__ import annotations

import re
import time
import uuid

import store
from bridge import Record, run_assembly
from pantheon import get_world


def _list(match, query, body):
    return 200, {"assemblies": store.assemblies(), "stats": store.stats()}


def _one(match, query, body):
    found = store.assembly(match.group("id"))
    if not found:
        return 404, {"error": "no such assembly", "id": match.group("id")}
    return 200, found


def _convene(match, query, body):
    body = body or {}
    kind = body.get("kind") or "townhall"
    topic = (body.get("topic") or "").strip()
    names = body.get("cis") or []
    if kind not in ("meeting", "dinner", "townhall"):
        return 400, {"error": "kind must be meeting, dinner or townhall"}
    if not topic:
        return 400, {"error": "empty topic"}
    if not isinstance(names, list):
        return 400, {"error": "cis must be a list of CI names"}
    names = list(dict.fromkeys(str(name).strip() for name in names if str(name).strip()))
    world = get_world()
    meeting_id = uuid.uuid4().hex
    try:
        record = Record()
        rows = record.q("SELECT name, tier, domain, fitness FROM agents WHERE status='active' "
                        "ORDER BY fitness DESC")
    except Exception:
        rows = []
    live_names = set()
    for row in rows:
        live_names.add(str(row["name"]).lower())
        world.register_agent(str(row["name"]), row["tier"] or "worker", row["domain"] or "world")
    world.remove_missing(live_names)
    names = [str(name).strip() for name in names if str(name).strip()]
    if names:
        missing = [name for name in names if name.lower() not in live_names]
        if missing:
            return 404, {"error": "no such CI: " + ", ".join(missing)}
    else:
        names = [row["name"] for row in rows[:6]]
    world.advance(time.time())
    attendees = world.begin_gathering(names, meeting_id, time.time())
    try:
        result = run_assembly(kind, topic, attendees, body.get("rounds"))
        if "error" in result:
            return result.get("status", 400), result
        saved = store.save_assembly(result)
        for line in saved.get("transcript") or []:
            if line.get("text"):
                world.record_speech(line.get("name", ""), line["text"], time.time(), kind="assembly")
        return 200, saved
    finally:
        world.end_gathering(meeting_id, time.time())
        world.advance(time.time())


ROUTES = [
    ("GET", re.compile(r"^/api/assemblies$"), _list),
    ("GET", re.compile(r"^/api/assembly/(?P<id>[\w.-]+)$"), _one),
    ("POST", re.compile(r"^/api/assembly$"), _convene),
]
