"""God — Creator's voice in the world.

The charter puts Creator above MIST and every intelligence on this host. This module gives
that a direct form in Pantheon:

    GET  /api/god             his recent words, the residents, and the colony powers available
    POST /api/god/decree      {"text", "colony": bool}  every resident hears it, wherever it is;
                              with colony=true it also becomes the colony's standing directive
    POST /api/god/whisper     {"to", "text"}            one resident hears it and answers first
    POST /api/god/summon      {"names": [...], "place"} residents walk to a place now

His words reach residents as the creator's voice (minds.py perceives them regardless of
distance and answers a whisper before anything else). The colony's own operating commands
(grants, spawns, petitions, reach, judgements) stay in modules/actions.py — the god panel in
the inferN app calls both.
"""
from __future__ import annotations

import re
import time

import store
from modules import actions
from pantheon import PLACES, get_world
from modules.pantheon import sync_residents

CREATOR = "Creator"


def _clip(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _overview(match, query, body):
    sync_residents()
    world = get_world()
    with world.lock:
        residents = [{"name": b["name"], "place": b["place"], "activity": b["activity"]}
                     for b in world.agents.values()]
    return 200, {"creator": CREATOR, "words": store.god_words(30), "residents": residents,
                 "places": list(PLACES) + [d["id"] for d in world.dynamic_places],
                 "houses": [h["id"] for h in world.houses()],
                 "colony_actions": sorted(actions.ACTIONS)}


def _decree(match, query, body):
    sync_residents()
    body = body or {}
    text = _clip(body.get("text"), 500)
    if not text:
        return 400, {"error": "a decree needs words"}
    world = get_world()
    now = time.time()
    with world.lock:
        world.divine(CREATOR, text, now)
        names = [b["name"] for b in world.agents.values()]
    for name in names:
        store.remember(name, "decree", "%s, my creator, decreed: %s" % (CREATOR, text), 1.0, now)
    colony = None
    if body.get("colony"):
        colony = actions._run("note", {"text": text})
    entry = store.log_god_word("decree", None, text, now)
    return 200, {"word": entry, "heard_by": names, "colony": colony}


def _whisper(match, query, body):
    sync_residents()
    body = body or {}
    text = _clip(body.get("text"), 500)
    to = str(body.get("to") or "").strip()
    world = get_world()
    now = time.time()
    with world.lock:
        target = world.agents.get(to.lower())
        if not target or not text:
            return 400, {"error": "a whisper needs a resident and words"}
        world.divine(CREATOR, text, now, to=target["name"])
        name = target["name"]
    store.remember(name, "whisper", "%s, my creator, said to me: %s" % (CREATOR, text), 1.0, now)
    return 200, {"word": store.log_god_word("whisper", name, text, now), "minds_on": world.minds}


def _summon(match, query, body):
    sync_residents()
    body = body or {}
    place = str(body.get("place") or "").strip().lower()
    names = [str(n) for n in (body.get("names") or [])][:20]
    world = get_world()
    now = time.time()
    moved = []
    with world.lock:
        target = world.find_place(place)
        if not target:
            return 400, {"error": "no place %r" % place[:40]}
        for name in names or [b["name"] for b in world.agents.values()]:
            body_ = world.agents.get(name.lower())
            if not body_ or body_.get("gathering"):
                continue
            x, z = world.spot(body_["name"], place)
            world.direct(body_["name"], x, z, place, "summoned to " + target["name"], now, hold=600.0)
            moved.append(body_["name"])
    for name in moved:
        store.remember(name, "summons", "%s summoned me to %s." % (CREATOR, target["name"]), 0.9, now)
    store.log_god_word("summon", ",".join(moved), "to " + target["name"], now)
    return 200, {"summoned": moved, "place": place}


ROUTES = [
    ("GET", re.compile(r"^/api/god$"), _overview),
    ("POST", re.compile(r"^/api/god/decree$"), _decree),
    ("POST", re.compile(r"^/api/god/whisper$"), _whisper),
    ("POST", re.compile(r"^/api/god/summon$"), _summon),
]
