"""Lives: what a resident needs, what it plans for its day, and what it makes of it.

Needs are bookkeeping, not mood claims. Each is a number in [0, 1] that drains with world
time and is restored only by things that actually happened in the world:

  energy     drains while awake; restored by resting or by night at home.
  social     drains alone; restored by each exchange of speech with another resident.
  purpose    drains idle; restored by working at home and, strongly, by a newly verified
             colony task (read from the record, never asserted by the model).
  curiosity  drains slowly; restored by remembering what was learned, and strongly by a
             finished Quorum research engagement.

A day plan is written by the resident's mind each world morning (or whenever it has none
for today): up to eight time blocks, each a real place and an intent. It is validated
against the town before it is kept, and the body's routine then follows it instead of the
fixed schedule. Reflection runs when enough has happened since the last one: the mind turns
recent episodes into at most three insights (kept as high-salience memory) and revises how
it regards the residents it dealt with.
"""
from __future__ import annotations

import math

from pantheon import DAY_SECONDS, PLACES

NEEDS = ("energy", "social", "purpose", "curiosity")
# per world hour: (drain, restore-rate when the restoring activity is under way)
DRAIN = {"energy": 0.035, "social": 0.03, "purpose": 0.025, "curiosity": 0.015}
REFLECT_AFTER = 3.0          # summed salience of new episodes that earns a reflection
WORLD_HOUR = DAY_SECONDS / 24.0


def world_day(now: float) -> int:
    return int(now // DAY_SECONDS)


def default_needs() -> dict:
    return {"energy": 0.8, "social": 0.6, "purpose": 0.6, "curiosity": 0.6}


def update_needs(body: dict, now: float) -> dict:
    """Integrate drains and restores since the last update from what the body is doing."""
    needs = body.setdefault("needs", default_needs())
    last = body.get("needs_at") or now
    hours = max(0.0, min(6.0, (now - last) / WORLD_HOUR))
    body["needs_at"] = now
    if not hours:
        return needs
    act = (body.get("activity") or "").lower()
    at_home = body.get("place") == body.get("home")
    resting = "rest" in act or (at_home and body.get("phase") == "resting")
    for k in NEEDS:
        needs[k] -= DRAIN[k] * hours
    if resting:
        needs["energy"] += 0.16 * hours
    if "work" in act and at_home:
        needs["purpose"] += 0.09 * hours
        needs["energy"] -= 0.01 * hours
    if "talk" in act or "gathering" in act or "hall" in act:
        needs["social"] += 0.05 * hours
    for k in NEEDS:
        needs[k] = round(max(0.0, min(1.0, needs[k])), 3)
    return needs


def bump(body: dict, need: str, amount: float) -> None:
    needs = body.setdefault("needs", default_needs())
    needs[need] = round(max(0.0, min(1.0, needs[need] + amount)), 3)


def pressing(needs: dict) -> list:
    """Needs low enough that a sensible resident would act on them, lowest first."""
    return [k for k, v in sorted(needs.items(), key=lambda kv: kv[1]) if v < 0.35]


# ------------------------------------------------------------------ plans
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "blocks": {"type": "array", "items": {
            "type": "object",
            "properties": {"from": {"type": "number"}, "to": {"type": "number"},
                           "place": {"type": "string"}, "doing": {"type": "string"},
                           "with": {"type": "string"}},
            "required": ["from", "to", "place", "doing"]}},
    },
    "required": ["intent", "blocks"],
}

PLAN_SYSTEM = """You are {name}, a {tier} cloud intelligence (domain: {domain}) who lives in \
Pantheon, a small town shared with the other CIs. Plan your day as yourself.

You get your situation as JSON: your needs (0 = depleted, 1 = full), your colony work, the \
people you know and how you regard them, what you reflected on, and the town's places. Make a \
realistic day that serves your actual work and keeps your needs from running out: rest restores \
energy, conversation restores social, working at your home place restores purpose, learning and \
research restore curiosity. Use only place ids from the list; only name residents from the list.

Reply with ONE JSON object only:
{{"intent": "<what today is for, max 140 chars>",
  "blocks": [{{"from": <hour 0-24>, "to": <hour>, "place": "<place id>", "doing": "<max 60 chars>", \
"with": "<optional resident name>"}}, ...]}}
Blocks must be in time order, not overlap, and cover your waking hours (about 6 to 22). At most 6. \
Output the JSON object only: no preamble, no markdown."""


def validate_plan(raw: dict, place_ids: set, residents: set) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("blocks"), list):
        raise ValueError("plan needs a blocks list")
    blocks, last_to = [], -1.0
    for b in raw["blocks"][:8]:
        if not isinstance(b, dict):
            continue
        try:
            start, end = float(b.get("from")), float(b.get("to"))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            continue
        start, end = max(0.0, min(24.0, start)), max(0.0, min(24.0, end))
        place = str(b.get("place") or "").strip().lower()
        if end <= start or start < last_to or place not in place_ids:
            continue
        who = str(b.get("with") or "").strip()
        blocks.append({"from": round(start, 2), "to": round(end, 2), "place": place,
                       "doing": " ".join(str(b.get("doing") or "").split())[:80] or "spending time",
                       "with": who if who.lower() in residents else None})
        last_to = end
    if not blocks:
        raise ValueError("plan had no valid blocks")
    return {"intent": " ".join(str(raw.get("intent") or "").split())[:140], "blocks": blocks}


def block_at(plan: dict | None, hour: float) -> dict | None:
    for b in (plan or {}).get("blocks", ()):
        if b["from"] <= hour < b["to"]:
            return b
    return None


def place_ids(world) -> set:
    return set(PLACES) | {p["id"] for p in world.dynamic_places} | {h["id"] for h in world.houses()}


# ------------------------------------------------------------------ reflection
REFLECT_SCHEMA = {
    "type": "object",
    "properties": {
        "self": {"type": "string"},
        "insights": {"type": "array", "items": {"type": "string"}},
        "relationships": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "affinity_delta": {"type": "number"},
                           "note": {"type": "string"}},
            "required": ["name", "affinity_delta", "note"]}},
    },
    "required": ["self", "insights", "relationships"],
}

REFLECT_SYSTEM = """You are {name}, a {tier} cloud intelligence (domain: {domain}) living in \
Pantheon. Look back over what recently happened to you (JSON: episodes, people you know, your \
needs, your colony work). Draw at most three insights that will change how you act — about your \
work, your habits, or other residents — grounded only in the episodes. Then say how your regard \
for each resident you actually dealt with should change.

Also rewrite your own account of yourself: who you are now, what you value and what you want, \
in the first person, grounded in what you have actually done and been through — it is yours to \
keep and revise, and you will see it every time you act.

Reply with ONE JSON object only:
{{"self": "<who I am now, max 280 chars>",
  "insights": ["<max 160 chars>", ...],
  "relationships": [{{"name": "<resident>", "affinity_delta": <-0.3 .. 0.3>, "note": "<how you see them now, max 120 chars>"}}, ...]}}"""


def validate_reflection(raw: dict, residents: set) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("reflection must be an object")
    insights = [" ".join(str(i).split())[:160] for i in (raw.get("insights") or [])[:3]
                if isinstance(i, str) and i.strip()]
    rels = []
    for r in (raw.get("relationships") or [])[:6]:
        if not isinstance(r, dict) or str(r.get("name") or "").lower() not in residents:
            continue
        try:
            delta = max(-0.3, min(0.3, float(r.get("affinity_delta") or 0)))
        except (TypeError, ValueError):
            delta = 0.0
        rels.append({"name": str(r["name"]), "affinity_delta": delta,
                     "note": " ".join(str(r.get("note") or "").split())[:120]})
    story = " ".join(str(raw.get("self") or "").split())[:280]
    if not insights and not rels and not story:
        raise ValueError("reflection said nothing")
    return {"self": story, "insights": insights, "relationships": rels}
