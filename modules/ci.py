"""One CI: opened up, and able to answer back.

GET  /api/ci/<name>            — the whole CI: identity, tier, brain, record, lineage
GET  /api/ci/<name>/note       — one file out of its own notebook (?path=)
GET  /api/ci/<name>/thread     — the conversation it has had with MIST
POST /api/ci/<name>/ask        — one live call: the CI answers MIST in its own voice
"""
from __future__ import annotations

import re

import store
from bridge import ci_view, notebook_note, talk_to_ci


def _ci(match, query, body):
    view = ci_view(match.group("name"))
    if view is None:
        return 404, {"error": "no such CI", "name": match.group("name")}
    view["thread"] = store.thread(match.group("name"))
    view["interactions"] = store.interactions_for_ci(match.group("name"))
    return 200, view


def _note(match, query, body):
    path = (query.get("path") or [""])[0]
    if not path:
        return 400, {"error": "path required"}
    result = notebook_note(match.group("name"), path)
    return (200 if "error" not in result else 404), result


def _thread(match, query, body):
    return 200, {"ci": match.group("name"), "thread": store.thread(match.group("name"))}


def _ask(match, query, body):
    body = body or {}
    result = talk_to_ci(match.group("name"), body.get("message") or "")
    if "error" in result:
        return result.get("status", 400), result
    saved = store.save_exchange(result)
    return 200, saved


ROUTES = [
    ("GET", re.compile(r"^/api/ci/(?P<name>[\w.-]+)$"), _ci),
    ("GET", re.compile(r"^/api/ci/(?P<name>[\w.-]+)/note$"), _note),
    ("GET", re.compile(r"^/api/ci/(?P<name>[\w.-]+)/thread$"), _thread),
    ("POST", re.compile(r"^/api/ci/(?P<name>[\w.-]+)/ask$"), _ask),
]
