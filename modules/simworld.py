"""SimWorld interface over the Pantheon world.

GET  /api/simworld          — the action space, places, and where each CI is
POST /api/simworld/command  — {agent, instruction}: parse the instruction (one metered
                              call) and execute it in the world
"""
from __future__ import annotations

import re
import time

from bridge import Record
from pantheon import get_world
from simworld_bridge import action_space, execute, parse, world_state
from modules import world_builder


def _sync_agents(world) -> dict:
    """Register every living CI into the world and return name -> {name, tier, ...}."""
    names = set()
    meta = {}
    try:
        record = Record()
        rows = record.q("SELECT name, tier, domain FROM agents WHERE status != 'retired'")
    except Exception:
        rows = []
    for r in rows:
        n = str(r["name"]).lower()
        names.add(n)
        meta[n] = {"name": r["name"], "tier": r["tier"] or "worker", "source": "colony"}
        world.register_agent(str(r["name"]), r["tier"] or "worker", r["domain"] or "world")
    # This resident is the Hermes profile, deliberately outside Colony economics.
    vinod = world_builder.OWNER.lower()
    names.add(vinod)
    meta[vinod] = {"name": world_builder.OWNER, "tier": "architect", "source": "hermes",
                   "profile": world_builder.PROFILE}
    world.register_agent(world_builder.OWNER, "architect", "world")
    world.agents[vinod]["profile"] = world_builder.PROFILE
    world.agents[vinod]["role"] = "owner of the dynamic world asset builder"
    world.remove_missing(names)
    return meta


def _simworld(match, query, body):
    world = get_world()
    _sync_agents(world)
    return 200, world_state()


def _command(match, query, body):
    body = body or {}
    name = (body.get("agent") or "").strip()
    instruction = (body.get("instruction") or "").strip()
    if not name or not instruction:
        return 400, {"error": "agent and instruction required"}

    world = get_world()
    meta = _sync_agents(world)
    now = time.time()
    world.advance(now)
    b = world.agents.get(name.lower())
    if not b:
        return 404, {"error": "no such agent", "agent": name,
                     "known": sorted(world.agents.keys())}

    agent = {"name": name, "tier": meta.get(name.lower(), {}).get("tier", "worker"),
             "place": b["place"], "x": round(b["x"], 1), "z": round(b["z"], 1)}
    parsed, meta2 = parse(agent, instruction)
    if parsed is None:
        return 502, {"error": meta2.get("error"), "model": meta2.get("model"),
                     "agent": name, "instruction": instruction}

    report = execute(name, parsed, world)
    return 200, {"agent": name, "instruction": instruction, "parsed": parsed,
                 "parser": meta2, "executed": report,
                 "snapshot": world.snapshot(time.time())}


ROUTES = [
    ("GET", re.compile(r"^/api/simworld$"), _simworld),
    ("POST", re.compile(r"^/api/simworld/command$"), _command),
]
