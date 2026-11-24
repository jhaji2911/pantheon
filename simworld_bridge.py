"""SimWorld's interaction interface, lifted onto Pantheon.

Faithful to SimWorld-AI/SimWorld's architecture (Apache-2.0), with exactly one part
swapped — the Communicator. In SimWorld the LocalPlanner turns a natural-language plan into
a HighLevelActionSpace ({destination, object_name, action_queue, reasoning}) and executes it
through a Communicator that drives Unreal Engine over a socket. Here the action space and
planner are the same shape, but the Communicator writes to Pantheon (the world our CIs live
in) instead of UnrealCV.

The metering is deliberate: nothing here spends tokens except an explicit `command`, which
is a single parser call. There is no autonomous loop.
"""
from __future__ import annotations

import json
import math
import re
import time

import bridge  # noqa: F401  (ensures COLONY_REPO on sys.path)
from colony import settings, transport
from pantheon import PLACES, SPEED, get_world

# ------------------------------------------------------------------- action space
HIGH_LEVEL_ACTIONS = {0: "DO_NOTHING", 1: "NAVIGATE", 2: "PICK_UP"}

ACTION_LIST = (
    "0: DO_NOTHING — do nothing.\n"
    "1: NAVIGATE — go to a named place in the world; must name the destination.\n"
    "2: PICK_UP — take an object; must name the object."
)

PARSER_SYSTEM_PROMPT = (
    "You are the action planner for a small colony of cloud intelligences living in a world. "
    "Translate an instruction into ONE structured action. Reply with a single JSON object and "
    "nothing else — no prose, no markdown fences."
)


def action_space() -> dict:
    return {"high_level": [{"value": k, "name": v} for k, v in HIGH_LEVEL_ACTIONS.items()],
            "list": ACTION_LIST}


def _places() -> list:
    return [{"id": k, "name": v["name"], "x": v["x"], "z": v["z"]}
            for k, v in PLACES.items()]


def _parser_user_prompt(agent: dict, instruction: str) -> str:
    place_lines = "\n".join(f"- {p['id']}: {p['name']} at ({p['x']}, {p['z']})" for p in _places())
    return (
        f"The resident is {agent['name']} (tier {agent['tier']}), now at {agent['place']} "
        f"(position {agent['x']}, {agent['z']}).\n\n"
        f"Places in the world:\n{place_lines}\n\n"
        f"Available actions:\n{ACTION_LIST}\n\n"
        f"Instruction: {instruction}\n\n"
        'Return JSON: {"destination": <place id or null>, "object_name": <or null>, '
        '"action_queue": [<ints>], "reasoning": "<why>"}'
    )


def parse(agent: dict, instruction: str) -> tuple:
    """One metered call: a natural-language instruction -> HighLevelActionSpace."""
    relay = transport.Relay()
    tier = agent.get("tier") or "worker"
    model = settings.TIERS[tier]["model"]
    messages = [
        {"role": "system", "content": PARSER_SYSTEM_PROMPT},
        {"role": "user", "content": _parser_user_prompt(agent, instruction)},
    ]
    result = relay.chat(model, messages, max_tokens=600, temperature=0.0, tier=tier)
    if not result.get("ok"):
        return None, {"error": result.get("error") or "model failed", "model": result.get("model")}
    content = result.get("content") or ""
    try:
        m = re.search(r"\{.*\}", content, re.S)
        data = json.loads(m.group(0))
    except Exception:
        return None, {"error": "unparseable response", "content": content[:300]}
    # coerce action_queue to ints
    queue = data.get("action_queue") or []
    data["action_queue"] = [int(a) for a in queue if str(a).isdigit()][:4]
    if not data["action_queue"]:
        data["action_queue"] = [0]
    meta = {"model": result.get("model"),
            "tokens": (result.get("usage") or {}).get("completion_tokens", 0)}
    return data, meta


def execute(agent_name: str, actions: dict, world=None) -> dict:
    """Apply a HighLevelActionSpace to the Pantheon world. Returns a report."""
    world = world or get_world()
    body = world.agents.get(agent_name.lower())
    if not body:
        return {"error": "no such agent", "status": 404}
    dest_id = actions.get("destination")
    obj = actions.get("object_name")
    queue = actions.get("action_queue") or []
    reports = []
    for act in queue:
        if act == 1:  # NAVIGATE
            p = PLACES.get(dest_id)
            if not p:
                reports.append({"error": f"unknown destination '{dest_id}'"})
                continue
            dx, dz = p["x"] - body["x"], p["z"] - body["z"]
            dist = math.hypot(dx, dz)
            now = time.time()
            body["since_x"], body["since_z"] = body["x"], body["z"]
            body["dest_x"], body["dest_z"] = p["x"], p["z"]
            body["depart_at"], body["arrive_at"] = now, now + dist / SPEED
            body["place"] = dest_id
            body["activity"] = "walking to " + p["name"]
            if dist > 0.01:
                body["fx"], body["fz"] = dx / dist, dz / dist
            reports.append({"action": "NAVIGATE", "to": dest_id, "distance": round(dist, 1)})
        elif act == 2:  # PICK_UP
            reports.append({"action": "PICK_UP", "object": obj,
                            "note": "no graspable objects in this world yet"})
        else:
            reports.append({"action": "DO_NOTHING"})
    world.save()
    return {"reports": reports, "position": [round(body["x"], 2), round(body["z"], 2)],
            "place": body["place"], "activity": body["activity"]}


def world_state() -> dict:
    """GET /api/simworld: the interface, the places, and where everyone is."""
    world = get_world()
    now = time.time()
    world.advance(now)
    snap = world.snapshot(now)
    snap["action_space"] = action_space()
    return snap
