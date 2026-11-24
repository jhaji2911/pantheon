"""Research proposals from Pantheon residents, approved by the principal and run by Quorum.

    GET  /api/research                   proposals, newest first, plus how to reach Quorum
    POST /api/research/<id>/approve      start the Quorum engagement (409 unless pending)
    POST /api/research/<id>/reject       {"reason": "..."} decline it; the proposer is told
    GET  /api/frontier?domain=quantum    the scored paper pool residents read, plus colony findings
    POST /api/frontier/refresh           fetch arXiv + OpenAlex now
    GET  /api/digest/preview?kind=daily|<proposal id>   build the PDF (no send)
    POST /api/digest/send                {"kind": "daily" | "<proposal id>"} send it to Telegram
"""
from __future__ import annotations

import re
import time
import time

import digest
import frontier
import digest
import frontier
import research
import store


def _list(match, query, body):
    status = (query.get("status") or [None])[0]
    return 200, {"proposals": store.research_proposals(status, 100), "quorum_url": research.QUORUM_URL}


def _approve(match, query, body):
    try:
        out = research.approve(int(match.group(1)))
    except research.QuorumUnavailable as exc:
        return 503, {"error": str(exc)}
    return int(out.pop("status", 200)), out


def _reject(match, query, body):
    out = research.reject(int(match.group(1)), str((body or {}).get("reason") or ""))
    return int(out.pop("status", 200)), out


def _frontier(match, query, body):
    domain = (query.get("domain") or [None])[0]
    return 200, {"papers": store.frontier_for(domain, 30, unused=False), "total": store.frontier_count(),
                 "notes": store.notes(20)}


def _frontier_refresh(match, query, body):
    return 200, frontier.refresh(force=True)


def _digest_preview(match, query, body):
    kind = (query.get("kind") or ["daily"])[0]
    if kind == "daily":
        caption, page = digest.daily_report(time.time() - digest.DAILY_EVERY)
    else:
        prop = store.research_proposal(int(kind))
        if not prop:
            return 404, {"error": "no such proposal"}
        caption, page = digest.research_report(prop)
    return 200, {"pdf": str(digest.render_pdf(page, "preview")), "caption": caption}


def _digest_send(match, query, body):
    kind = str((body or {}).get("kind") or "daily")
    if kind == "daily":
        store.kv_set("digest_daily", "0")
        return 200, digest.maybe_daily() or {"sent": False, "error": "digest disabled (MIST_DIGEST=0)"}
    return 200, digest.send_research(int(kind))


def _frontier(match, query, body):
    domain = (query.get("domain") or [None])[0]
    return 200, {"papers": store.frontier_for(domain, 30, unused=False), "total": store.frontier_count(),
                 "notes": store.notes(20)}


def _frontier_refresh(match, query, body):
    return 200, frontier.refresh(force=True)


def _digest_preview(match, query, body):
    kind = (query.get("kind") or ["daily"])[0]
    if kind == "daily":
        caption, page = digest.daily_report(time.time() - digest.DAILY_EVERY)
    else:
        prop = store.research_proposal(int(kind))
        if not prop:
            return 404, {"error": "no such proposal"}
        caption, page = digest.research_report(prop)
    return 200, {"pdf": str(digest.render_pdf(page, "preview")), "caption": caption}


def _digest_send(match, query, body):
    kind = str((body or {}).get("kind") or "daily")
    if kind == "daily":
        store.kv_set("digest_daily", "0")
        return 200, digest.maybe_daily() or {"sent": False, "error": "digest disabled (MIST_DIGEST=0)"}
    return 200, digest.send_research(int(kind))


ROUTES = [
    ("GET", re.compile(r"^/api/frontier$"), _frontier),
    ("POST", re.compile(r"^/api/frontier/refresh$"), _frontier_refresh),
    ("GET", re.compile(r"^/api/digest/preview$"), _digest_preview),
    ("POST", re.compile(r"^/api/digest/send$"), _digest_send),
    ("GET", re.compile(r"^/api/frontier$"), _frontier),
    ("POST", re.compile(r"^/api/frontier/refresh$"), _frontier_refresh),
    ("GET", re.compile(r"^/api/digest/preview$"), _digest_preview),
    ("POST", re.compile(r"^/api/digest/send$"), _digest_send),
    ("GET", re.compile(r"^/api/research$"), _list),
    ("POST", re.compile(r"^/api/research/(\d+)/approve$"), _approve),
    ("POST", re.compile(r"^/api/research/(\d+)/reject$"), _reject),
]
