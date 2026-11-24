"""Residents' research and build proposals, carried out by Quorum after the principal approves.

A resident's mind may `propose_research` (a question it needs evidence for) or propose a
build. Nothing runs until Creator approves it in the console. An approved proposal becomes
one Quorum engagement through Company Control's own API (`POST /api/engagement`), so it is
staffed, investigated with real search and arithmetic, verified, and adjudicated exactly as
any other Quorum engagement; a build uses Quorum's software profile and engineering handoff.

`poll()` follows running engagements. When one closes, the proposer is told the verdict and
the paper's opening, which become a high-salience memory and restore its curiosity; the
paper path is kept so the resident (and anyone reading its mind) can cite it.
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import time
import urllib.error
import urllib.request

import frontier
import digest
import frontier
import store

QUORUM_URL = os.environ.get("MIST_QUORUM_URL", "http://127.0.0.1:8787").rstrip("/")
QUORUM_REPO = pathlib.Path.home() / "Code" / "quorum"
KINDS = ("research", "build")


class QuorumUnavailable(RuntimeError):
    pass


def _call(method, path, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(QUORUM_URL + path, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("error") or str(exc)
        except Exception:                                        # noqa: BLE001
            msg = str(exc)
        raise QuorumUnavailable("Quorum refused: %s" % msg) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise QuorumUnavailable("Quorum Company Control is not reachable at %s (start it with "
                                "~/Code/quorum/start_quorum.sh): %s" % (QUORUM_URL, exc)) from exc


def approve(pid: int) -> dict:
    """Start the Quorum engagement for a pending proposal. Raises QuorumUnavailable."""
    prop = store.research_proposal(pid)
    if not prop:
        return {"error": "no such proposal", "status": 404}
    if prop["status"] != "pending":
        return {"error": "proposal is %s, not pending" % prop["status"], "status": 409}
    build = prop["kind"] == "build"
    out = _call("POST", "/api/engagement", {
        "topic": frontier.quorum_topic(prop), "rounds": 1, "revisions": 1, "write_paper": True,
        "handoff": build, "profile": "software" if build else "research",
        "output": "app" if build else "library",
    })
    store.update_research(pid, status="running", decided=time.time(), job_id=out.get("job_id"), error=None)
    store.remember(prop["name"], "research",
                   "Creator approved my %s proposal; Quorum started on: %s" % (prop["kind"], prop["topic"][:160]),
                   0.8)
    return {"proposal": store.research_proposal(pid), "quorum": out, "status": 202}


def reject(pid: int, reason: str = "") -> dict:
    prop = store.research_proposal(pid)
    if not prop:
        return {"error": "no such proposal", "status": 404}
    if prop["status"] != "pending":
        return {"error": "proposal is %s, not pending" % prop["status"], "status": 409}
    store.update_research(pid, status="rejected", decided=time.time(), error=reason[:300] or None)
    store.remember(prop["name"], "research", "Creator declined my %s proposal on %s%s" %
                   (prop["kind"], prop["topic"][:120], (": " + reason[:120]) if reason else ""), 0.7)
    return {"proposal": store.research_proposal(pid), "status": 200}


def _paper_opening(path: str | None, limit: int = 900) -> str:
    if not path:
        return ""
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = QUORUM_REPO / p
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return ""
    return " ".join(text.split())[:limit]


def _deliver(pid: int) -> None:
    """Render the finished paper to PDF and send it to Creator's Telegram (off the mind loop)."""
    try:
        digest.send_research(pid)
    except Exception:                                             # noqa: BLE001 - retried by send_pending_research
        pass


def poll(on_done=None) -> int:
    """Advance every running proposal from Quorum's record. Returns how many finished."""
    running = store.research_proposals("running")
    if not running:
        return 0
    try:
        jobs = {j.get("id"): j for j in _call("GET", "/api/jobs").get("jobs", [])}
    except QuorumUnavailable:
        return 0
    finished = 0
    for prop in running:
        job = jobs.get(prop["job_id"]) or {}
        eid = prop.get("engagement_id") or job.get("engagement_id")
        if eid and not prop.get("engagement_id"):
            store.update_research(prop["id"], engagement_id=int(eid))
        if job.get("status") in ("failed", "stopped"):
            store.update_research(prop["id"], status="failed", error="Quorum job %s" % job.get("status"))
            store.remember(prop["name"], "research", "Quorum's work on my proposal %s: %s" %
                           (job.get("status"), prop["topic"][:120]), 0.7)
            finished += 1
            continue
        if not eid:
            continue
        try:
            eng = _call("GET", "/api/engagement/%d" % int(eid)).get("engagement") or {}
        except QuorumUnavailable:
            continue
        if eng.get("status") != "closed":
            continue
        opening = _paper_opening(eng.get("paper_path"))
        verdict = eng.get("verdict") or "no verdict"
        store.update_research(prop["id"], status="done", verdict=verdict,
                              paper_path=eng.get("paper_path"), summary=opening or None)
        store.remember(prop["name"], "research",
                       "Quorum finished my question '%s': verdict %s. %s" %
                       (prop["topic"][:100], verdict, opening[:220]), 1.0)
        store.add_note(prop["name"], "finding",
                       "%s -> %s. %s" % (prop["topic"][:140], verdict, opening[:300]),
                       prop["id"], [prop["paper"]] if prop.get("paper") else [])
        store.add_note(prop["name"], "finding",
                       "%s -> %s. %s" % (prop["topic"][:140], verdict, opening[:300]),
                       prop["id"], [prop["paper"]] if prop.get("paper") else [])
        threading.Thread(target=_deliver, args=(prop["id"],), daemon=True).start()
        if on_done:
            on_done(prop["name"])
        finished += 1
    return finished
