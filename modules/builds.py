"""Builds — apps made by Quorum's engineering company, shown and commissioned from here.

    GET  /api/builds          every software engagement Quorum has run (verdict, builder, files,
                              previewable web app), what Quorum is working on now, and whether
                              the DSH builder is ready
    POST /api/builds          {"brief", "builder": "dsh"|"free"} start one software engagement
                              that delivers a runnable app (Quorum runs one engagement at a time)

Quorum's record is read `mode=ro` from its own database and run folders; commissioning goes
through Company Control's API exactly as its own dashboard does. A previewable build is
served by Quorum at /app/<engagement>/ and can be embedded by the inferN app when Quorum was
started there (QUORUM_FRAME_ANCESTORS).
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3

import research

QUORUM_DB = research.QUORUM_REPO / "quorum.db"
RUNS = research.QUORUM_REPO / "runs"
DSH_ENTRY = pathlib.Path.home() / "tools" / "deepseek-harness" / "apps" / "cli" / "lib" / "bin.js"


def _builds(limit=30):
    if not QUORUM_DB.is_file():
        return []
    conn = sqlite3.connect("file:%s?mode=ro" % QUORUM_DB, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, topic, status, verdict, opened_on, closed_on FROM engagements "
                            "ORDER BY id DESC LIMIT 200").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        run = next(iter(sorted(RUNS.glob("e%03d-*" % r["id"]))), None)
        manifest = run / "build-manifest.json" if run else None
        if not manifest or not manifest.is_file():
            continue                       # research-only engagement: no build
        try:
            m = json.loads(manifest.read_text())
        except (OSError, ValueError):
            m = {}
        out.append({"id": r["id"], "topic": r["topic"], "status": r["status"],
                    "verdict": m.get("verdict") or r["verdict"], "builder": m.get("builder"),
                    "output": m.get("output"), "files": len(m.get("files") or []),
                    "tickets": len(m.get("tickets") or []), "has_app": bool(m.get("has_app")),
                    "app_url": "%s/app/%d/" % (research.QUORUM_URL, r["id"]) if m.get("has_app") else None,
                    "builder_error": m.get("builder_error"), "run_dir": str(run)})
        if len(out) >= limit:
            break
    return out


def _list(match, query, body):
    try:
        jobs = research._call("GET", "/api/jobs")
        up, error = True, None
    except research.QuorumUnavailable as exc:
        jobs, up, error = {}, False, str(exc)
    active = [j for j in jobs.get("jobs", []) if j.get("status") == "running"]
    return 200, {"quorum_url": research.QUORUM_URL, "quorum_up": up, "error": error,
                 "dsh_ready": DSH_ENTRY.is_file(), "busy": (jobs.get("runner") or {}).get("busy"),
                 "active": active, "builds": _builds()}


def _commission(match, query, body):
    body = body or {}
    brief = " ".join(str(body.get("brief") or "").split())
    builder = "dsh" if str(body.get("builder") or "dsh").lower() == "dsh" else "free"
    if not 20 <= len(brief) <= 500:
        return 400, {"error": "describe the app in 20–500 characters"}
    if builder == "dsh" and not DSH_ENTRY.is_file():
        return 409, {"error": "the DeepSeek Harness is not built (~/tools/deepseek-harness)"}
    try:
        out = research._call("POST", "/api/engagement", {
            "topic": brief, "rounds": 1, "revisions": 1, "write_paper": True, "handoff": True,
            "profile": "software", "output": "app", "builder": builder})
    except research.QuorumUnavailable as exc:
        return 503, {"error": str(exc)}
    return 202, {"job": out, "builder": builder}


ROUTES = [
    ("GET", re.compile(r"^/api/builds$"), _list),
    ("POST", re.compile(r"^/api/builds$"), _commission),
]
