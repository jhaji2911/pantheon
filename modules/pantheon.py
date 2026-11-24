"""Pantheon: the world the CIs live in — embodied, with homes and habits.

Reads the colony's roster (read-only) and syncs each CI into a body in the world,
then advances the world to now and reports where everyone is and what they are doing.
The world state is the console's own (pantheon.json), never written to the colony.

The brain (`minds`) is the metered layer: off by default. When on, a background loop
lets each CI decide and act on its own — the world runs itself.
"""
from __future__ import annotations

import re
import threading
import time

from bridge import Record
from pantheon import get_world
import minds
from worldgen import refresh as refresh_world
import store
from modules import world_builder

BRAIN_TICK = 6.0        # seconds between background mind advances
_brain_started = False
_brain_lock = threading.Lock()


def _brain_loop():
    # At most one CI thinks per tick; minds.tick gates spend and never runs while
    # an HTTP request holds the world.
    while True:
        try:
            minds.tick(get_world(), time.time())
        except Exception as exc:
            minds._state["last_error"] = "%s: %s" % (type(exc).__name__, exc)
        time.sleep(BRAIN_TICK)


def _ensure_brain():
    global _brain_started
    with _brain_lock:
        if not _brain_started:
            threading.Thread(target=_brain_loop, daemon=True).start()
            _brain_started = True


def sync_residents():
    """Register every colony resident (and Vinod) as a body; returns the Record or None.

    A failed roster read leaves the world as it is: removing residents on a transient read
    error would wipe their plans and needs."""
    world = get_world()
    try:
        record = Record()
        rows = record.q("SELECT name, tier, domain FROM agents WHERE status != 'retired'")
    except Exception:
        return None
    names = set()
    with world.lock:
        for r in rows:
            names.add(str(r["name"]).lower())
            world.register_agent(str(r["name"]), r["tier"] or "worker", r["domain"] or "world")
        # Vinod Chanda is the cc-operator Hermes profile, not a fabricated Colony citizen.
        # Keep his world body/profile identity separate from the read-only Colony roster.
        owner_key = world_builder.OWNER.lower()
        names.add(owner_key)
        world.register_agent(world_builder.OWNER, "architect", "world")
        world.agents[owner_key]["profile"] = world_builder.PROFILE
        world.agents[owner_key]["role"] = "owner of the dynamic world asset builder"
        world.remove_missing(names)
    return record


def _pantheon(match, query, body):
    _ensure_brain()
    world = get_world()
    record = sync_residents()
    if record:
        try:
            generated=refresh_world(record)
            world.dynamic_places=generated["places"]
            world.artifacts=generated["artifacts"]
            world.assets=store.world_assets(250)
            world_builder.start_autobuilder()
        except Exception as exc:
            world.generation_error=str(exc)[:240]
    now = time.time()
    with world.lock:
        world.advance(now)
        return 200, world.snapshot(now)


def _minds(match, query, body):
    _ensure_brain()
    world = get_world()
    body = body or {}
    if "on" in body:
        world.set_minds(bool(body["on"]))
    return 200, {"minds": world.minds, "agents": len(world.agents), **minds.status()}


def _mind_log(match, query, body):
    name = (query.get("name") or [None])[0]
    try:
        limit = max(1, min(200, int((query.get("limit") or [30])[0])))
    except ValueError:
        limit = 30
    life = None
    if name:
        body = get_world().agents.get(name.lower())
        saved = store.load_life(name) or {}
        life = {"needs": (body or {}).get("needs") or saved.get("needs"),
                "plan": (body or {}).get("plan") or saved.get("plan"),
                "goal": (body or {}).get("goal") or saved.get("goal"),
                "self_story": (body or {}).get("self_story") or saved.get("self_story"),
                "relations": store.relations_of(name, 12),
                "research": store.research_proposals(name=name, limit=5)}
    return 200, {"status": minds.status(), "log": store.mind_log(name, limit),
                 "episodes": store.recall_episodes(name, 20) if name else [], "life": life}


ROUTES = [
    ("GET", re.compile(r"^/api/pantheon$"), _pantheon),
    ("POST", re.compile(r"^/api/pantheon/minds$"), _minds),
    ("GET", re.compile(r"^/api/pantheon/minds$"), _minds),
    ("GET", re.compile(r"^/api/pantheon/minds/log$"), _mind_log),
]
