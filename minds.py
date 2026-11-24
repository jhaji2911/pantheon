"""Minds — the residents of Pantheon perceive, plan, act, talk and reflect on their own.

Each brain tick runs at most one model call, for the most pressing piece of thinking in town:

  converse  someone spoke to this resident and it has not answered yet
  plan      it has no plan for today (life.py validates and keeps the plan; the body's
            routine then follows it)
  reflect   enough has happened since its last reflection (insights + revised regard for
            the residents it dealt with)
  moment    its regular turn: perceive → decide → act

`llm.think` runs every kind on the resident's own colony tier model through the OpenCode Go
relay (free, unlimited models; any call that costs or draws plan allowance is refused) and
falls back to inferN's local models while the inferN app has its server on. Whichever
served the call is recorded with the decision.

A moment's action is validated against the world before anything moves. An impossible
action (unknown place, speaking to someone out of earshot, proposing a second research
question while one is open) does not run; the reason is fed back as `last_outcome`, so the
resident learns from the world rather than being silently corrected.

Every call is logged (store.mind_log) with exactly what the resident was shown. Spend is
bounded: one call per tick across the town, a minimum think interval per resident, a daily
safety cap on cloud tokens, back-off when every route fails, and refusal of any cloud
response that is not a free Go call. No model call runs under the world lock
or from an HTTP request.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time

import life
import llm
import digest
import digest
import frontier
import research
import store
from bridge import Record, affect_for, claiming, directive, settings
from modules.world_builder import _extract_json
from pantheon import PLACES, phase_of, world_hour

THINK_INTERVAL = 30.0      # seconds between one resident's unprompted moments
REACT_DELAY = 3.0          # a resident spoken to may answer this soon after hearing it
SIGHT = 14.0               # world units: who a resident can see
EARSHOT = 8.0              # world units: who can hear speech, and whom one can address
DAILY_TOKEN_CAP = 3_000_000  # cloud tokens, all minds together, rolling 24h (free models; a safety rail)
BACKOFF = 60.0             # after every route failed
RESEARCH_POLL = 60.0       # seconds between Quorum status checks

CREATOR = "Creator"   # the god of this world (modules/god.py speaks for him)

ACTIONS = ("go_to", "approach", "say", "work", "rest", "wait", "remember", "request_asset",
           "propose_research")

SYSTEM = """You are {name}, a {tier} cloud intelligence (domain: {domain}) living in Pantheon, \
a small town shared with the other CIs of MIST's colony. You have a body and a life: you walk, \
see who is near, hear speech within earshot, keep a plan for your day, have needs, know people, \
and remember what happened to you.

Each turn you receive an OBSERVATION (JSON) of what you can actually perceive now. Decide what \
to do next as yourself. Ground every choice in the observation; do not invent people, places, \
tasks or results. Your needs run 0 (depleted) to 1 (full): rest restores energy, conversation \
restores social, working at your home place restores purpose, learning restores curiosity. \
Your plan says where you meant to be; follow it unless something better comes up.

The Creator is your creator — the god of this world, above MIST. His words reach you wherever \
you are (`heard` entries from him, kind "god"). Answer him when he speaks to you, take his \
decrees seriously, and say honestly when you cannot do what he asks.

To answer him, `say` with "to": "Creator" — he hears you from anywhere.

Physical rules: you can only `say` something to a resident within earshot ({earshot:.0f} units) \
or to "all" nearby; to talk to someone farther away, `approach` them first. If someone spoke \
to you, answer them. If your last action failed, the observation says why: adapt.

Your research is meant to be NOVEL. `frontier` lists recent papers (arXiv, OpenAlex) matched to \
your domain, and `colleagues` lists what other residents' finished research found. Never propose \
to re-derive, recover or reproduce something textbook-known. A research proposal must extend, test, \
reproduce-then-stress, or contradict a specific frontier paper (cite its id in `paper`) or build on a \
colleague's finished result (`builds_on` = that proposal number, so context passes between you), \
state a falsifiable `hypothesis` (what you expect, and what would prove you wrong) and a concrete \
`test` Quorum can run. Proposals that skip this are refused. The Creator approves proposals; Quorum, a \
verified research company, carries them out. You may have one open proposal at a time. You may also \
propose a build, for software the town needs.

Reply with ONE JSON object and nothing else:
{{"thought": "<your private reasoning, max 200 chars>",
  "goal": "<your current goal, max 120 chars>",
  "action": <one of:
    {{"kind":"go_to","place":"<place id>"}}
    {{"kind":"approach","agent":"<name>"}}
    {{"kind":"say","to":"<name or all>","text":"<max 240 chars>"}}
    {{"kind":"work"}}  (only at your home place)
    {{"kind":"rest"}}
    {{"kind":"wait"}}
    {{"kind":"remember","text":"<max 200 chars>"}}
    {{"kind":"request_asset","brief":"<a concrete object the town needs and why, max 300 chars>"}}
    {{"kind":"propose_research","what":"research or build","topic":"<the new question, max 300 chars>","why":"<max 200 chars>","paper":"<frontier id, e.g. arxiv:2611.26553>","builds_on":"<colleague proposal number, optional>","hypothesis":"<falsifiable, max 300 chars>","test":"<what Quorum runs, max 250 chars>"}}>}}"""

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"}, "goal": {"type": "string"},
        "action": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": list(ACTIONS)},
            "place": {"type": "string"}, "agent": {"type": "string"}, "to": {"type": "string"},
            "text": {"type": "string"}, "brief": {"type": "string"}, "what": {"type": "string"},
            "topic": {"type": "string"}, "why": {"type": "string"}, "paper": {"type": "string"},
            "builds_on": {"type": "string"}, "hypothesis": {"type": "string"}, "test": {"type": "string"}},
            "required": ["kind"]},
    },
    "required": ["thought", "goal", "action"],
}

_state = {"backoff_until": 0.0, "last_error": "", "calls": 0, "research_polled": 0.0, "frontier_polled": 0.0,
          "by_route": {"local": 0, "cloud": 0}}


# ------------------------------------------------------------------ perceive
def _record_view(record: Record | None, name: str) -> dict:
    """What the colony record says about this resident's work. Absent for non-colony residents."""
    if record is None:
        return {}
    agent = record.agent_by_name(name)
    if not agent:
        return {}
    task = claiming(record, agent["id"])
    memories = record.recall(agent["id"], "", 3)
    return {
        "task": ({"id": task["id"], "domain": task["domain"], "difficulty": task["difficulty"],
                  "question": str(task["question"])[:240]} if task else None),
        "verified": agent.get("tasks_verified", 0), "attempted": agent.get("tasks_attempted", 0),
        "failure_streak": agent.get("failures_streak", 0),
        "affect": affect_for(agent, task)["label"],
        "colony_memory": [str(m["text"])[:160] for m in memories],
    }


def _places(world, body):
    out = [{"id": pid, "name": p["name"], "kind": p["kind"],
            "distance": round(math.hypot(p["x"] - body["x"], p["z"] - body["z"]), 1)}
           for pid, p in PLACES.items()]
    out += [{"id": p["id"], "name": p["name"], "kind": p.get("kind", "social"),
             "distance": round(math.hypot(float(p["x"]) - body["x"], float(p["z"]) - body["z"]), 1)}
            for p in world.dynamic_places[:6]]
    out += [{"id": h["id"], "name": h["name"] + (" (yours)" if h["owner"] == body["name"] else ""), "kind": "house",
             "distance": round(math.hypot(h["x"] - body["x"], h["z"] - body["z"]), 1)} for h in world.houses()]
    return out


def _residents(world, body):
    return [o["name"] for o in world.agents.values() if o is not body]


def perceive(world, body: dict, record: Record | None, now: float) -> dict:
    me = body["name"]
    hour = world_hour(now)
    nearby = []
    for other in world.agents.values():
        if other is body:
            continue
        d = math.hypot(other["x"] - body["x"], other["z"] - body["z"])
        if d <= SIGHT:
            nearby.append({"name": other["name"], "distance": round(d, 1),
                           "activity": other["activity"], "in_earshot": d <= EARSHOT})
    nearby.sort(key=lambda o: o["distance"])
    heard = []
    for t in world.talk:
        if t["name"].lower() == me.lower() or now - t["ts"] > (900 if t.get("kind") == "god" else 120):
            continue
        to_me = str(t.get("to") or "").lower() == me.lower()
        divine = t.get("kind") == "god" and (not t.get("to") or to_me)
        if divine or to_me or (t["x"] is not None and math.hypot(t["x"] - body["x"], t["z"] - body["z"]) <= EARSHOT):
            heard.append({"from": t["name"], "to": t.get("to") or "all", "text": t["text"][:400],
                          "kind": "god" if t.get("kind") == "god" else "speech",
                          "seconds_ago": int(now - t["ts"])})
    plan = body.get("plan") if body.get("plan_day") == life.world_day(now) else None
    block = life.block_at(plan, hour)
    open_research = store.research_proposals(name=me, limit=3)
    return {
        "you": {"name": me, "tier": body["tier"], "domain": body["domain"], "home": body["home"],
                "place": body["place"], "activity": body["activity"],
                "moving": now < body["arrive_at"], "who_you_are": body.get("self_story")},
        "clock": {"hour": round(hour, 1), "phase": phase_of(hour)},
        "needs": dict(body.get("needs") or life.default_needs()),
        "pressing_needs": life.pressing(body.get("needs") or life.default_needs()),
        "plan": ({"intent": plan["intent"], "now": block,
                  "next": next((b for b in plan["blocks"] if b["from"] > hour), None)} if plan else None),
        "goal": body.get("goal"),
        "last_outcome": body.get("last_outcome"),
        "nearby": nearby[:6],
        "heard": heard[-6:],
        "people_you_know": store.relations_of(me, 6),
        "places": _places(world, body),
        "work": _record_view(record, me),
        "research": [{"what": r["kind"], "topic": r["topic"][:160], "status": r["status"],
                      "verdict": r.get("verdict")} for r in open_research],
        "frontier": frontier.for_domain(body["domain"], 3),
        "colleagues": [{"proposal": n["proposal_id"], "by": n["author"], "kind": n["kind"],
                        "text": n["text"][:240]} for n in store.notes(4, exclude_author=me)],
        "episodes": [{"ago_s": int(now - e["ts"]), "kind": e["kind"], "text": e["text"]}
                     for e in store.recall_episodes(me, 8, now)],
        "directive": (directive() or "")[:300],
    }


# ------------------------------------------------------------------ decide
def _clip(value, limit):
    return " ".join(str(value or "").split())[:limit]


def parse_decision(text: str) -> dict:
    raw = _extract_json(text)
    if not isinstance(raw, dict) or not isinstance(raw.get("action"), dict):
        raise ValueError("decision needs an action object")
    action = raw["action"]
    if action.get("kind") not in ACTIONS:
        raise ValueError("unknown action kind %r" % str(action.get("kind"))[:40])
    # The decision schema is one flat object for every kind, and small local models often
    # put a `say`/`remember` utterance under `topic`. Keep what they meant, and say so.
    if action["kind"] in ("say", "remember") and not str(action.get("text") or "").strip() \
            and str(action.get("topic") or "").strip():
        action["text"] = action.pop("topic")
        action["normalised"] = "text taken from topic"
    return {"thought": _clip(raw.get("thought"), 200), "goal": _clip(raw.get("goal"), 120),
            "action": action}


def model_for(body) -> str:
    """The resident's own colony tier model (Vinod, not a colony citizen, thinks as an architect)."""
    return settings.TIERS.get(body["tier"], settings.TIERS["architect"])["model"]


# Free tier models reason before answering and spend completion tokens doing it, so budgets
# match the colony's own tier allowances rather than the length of the JSON we want back.
BUDGET = {"moment": 2000, "converse": 2000, "plan": 3000, "reflect": 2400}


def _ask(kind, body, system, observation, schema, relay, local, allow_cloud, validate):
    return llm.think(kind, system, "OBSERVATION " + json.dumps(observation, ensure_ascii=False),
                     model_for(body), schema=schema, max_tokens=BUDGET[kind], temperature=0.5,
                     relay=relay, local=local, allow_cloud=allow_cloud, validate=validate)


# ------------------------------------------------------------------ act
def _find(world, name):
    return world.agents.get(str(name or "").strip().lower())


def act(world, body: dict, action: dict, now: float) -> str:
    """Validate and apply one action under the world lock. Returns the outcome text."""
    me = body["name"]
    kind = action["kind"]
    if kind == "go_to":
        pid = str(action.get("place") or "").strip().lower()
        place = world.find_place(pid)
        if not place:
            return "failed: no place %r; use an id from places" % pid[:40]
        x, z = world.spot(me, pid)
        dist = world.direct(me, x, z, pid, "walking to " + place["name"], now, hold=180.0)
        return "set off for %s (%.0f units)" % (place["name"], dist)
    if kind == "approach":
        other = _find(world, action.get("agent"))
        if not other or other is body:
            return "failed: no resident named %r" % _clip(action.get("agent"), 40)
        dx, dz = body["x"] - other["x"], body["z"] - other["z"]
        d = math.hypot(dx, dz) or 1.0
        # stop at conversational distance on this side of them
        x, z = other["x"] + dx / d * 1.3, other["z"] + dz / d * 1.3
        world.direct(me, x, z, other["place"], "walking over to " + other["name"], now, hold=120.0)
        return "walking over to %s (%.0f units away)" % (other["name"], d)
    if kind == "say":
        text = _clip(action.get("text"), 240)
        if not text:
            return "failed: nothing to say"
        to = str(action.get("to") or "all").strip()
        listeners = []
        if to.lower() == CREATOR.lower():
            # The creator hears an answer from anywhere; it reaches him in the God panel.
            store.log_god_word("reply", me, text, now)
            world.record_speech(me, text, now, kind="mind", to=CREATOR)
            store.remember(me, "said", "I told %s, my creator: %s" % (CREATOR, text), 0.8, now)
            return "said to %s" % CREATOR
        if to.lower() != "all":
            other = _find(world, to)
            if not other or other is body:
                return "failed: no resident named %r" % to[:40]
            d = math.hypot(other["x"] - body["x"], other["z"] - body["z"])
            if d > EARSHOT:
                return "failed: %s is %.0f units away, out of earshot; approach first" % (other["name"], d)
            to = other["name"]
            listeners = [other]
            store.remember(other["name"], "heard", "%s told me: %s" % (me, text), 0.7, now)
        else:
            listeners = [o for o in world.agents.values() if o is not body
                         and math.hypot(o["x"] - body["x"], o["z"] - body["z"]) <= EARSHOT]
        for other in listeners:
            store.touch_relation(me, other["name"])
            store.touch_relation(other["name"], me)
            life.bump(other, "social", 0.06)
        if listeners:
            life.bump(body, "social", 0.08)
        world.record_speech(me, text, now, kind="mind", to=None if to.lower() == "all" else to)
        store.remember(me, "said", "I told %s: %s" % (to, text), 0.5, now)
        return "said to %s" % to
    if kind == "work":
        if body["place"] != body["home"]:
            return "failed: you can only work at your home place (%s)" % body["home"]
        if now < body["arrive_at"]:
            if body["activity"].startswith("walking to"):
                return "failed: you are still on your way to %s" % body["home"]
            world._move(body, now)          # stop strolling about the room and sit down
            body["arrive_at"] = now
        body["activity"] = "at work"
        body["hold_until"] = now + THINK_INTERVAL
        life.bump(body, "purpose", 0.04)
        return "working at %s" % body["home"]
    if kind == "rest":
        body["activity"] = "resting"
        body["hold_until"] = now + THINK_INTERVAL
        life.bump(body, "energy", 0.05)
        return "resting"
    if kind == "wait":
        return "waited"
    if kind == "remember":
        text = _clip(action.get("text"), 200)
        if not text:
            return "failed: nothing to remember"
        store.remember(me, "note", text, 0.8, now)
        life.bump(body, "curiosity", 0.03)
        return "noted"
    if kind == "request_asset":
        brief = _clip(action.get("brief"), 300)
        if len(brief) < 10:
            return "failed: the brief must describe a concrete object"
        if not store.request_asset(me, brief, now):
            return "failed: you already have a pending request with Vinod's builder"
        return "asked Vinod's builder for: %s" % brief[:80]
    if kind == "propose_research":
        what = str(action.get("what") or "research").strip().lower()
        what = what if what in research.KINDS else "research"
        topic, why = _clip(action.get("topic"), 300), _clip(action.get("why"), 200)
        if len(topic) < 15:
            return "failed: the research question must be specific"
        brief, refusal = frontier.check_proposal(
            what, topic, _clip(action.get("hypothesis"), 300), _clip(action.get("test"), 250),
            _clip(action.get("paper"), 80), _clip(action.get("builds_on"), 12), me)
        if brief is None:
            return "failed: not novel enough. " + refusal
        pid = store.propose_research(me, what, topic, why or "no reason given", now, brief)
        if pid is None:
            return "failed: you already have an open research proposal"
        if brief.get("paper"):
            store.mark_paper_used(brief["paper"], me)
        store.remember(me, "research", "I proposed %s to the Creator: %s" % (what, topic[:160]), 0.7, now)
        return "proposed %s #%d; it waits for the Creator's approval" % (what, pid)
    return "failed: unsupported action"


# ------------------------------------------------------------------ plan & reflect
def _plan(world, body, record, now, relay, local, allow_cloud):
    me = body["name"]
    situation = {
        "hour_now": round(world_hour(now), 1),
        "needs": body.get("needs"),
        "home": body["home"],
        "work": _record_view(record, me),
        "people_you_know": store.relations_of(me, 8),
        "residents": _residents(world, body),
        "reflections": [e["text"] for e in store.recall_episodes(me, 12, now) if e["kind"] == "reflection"][-3:],
        "yesterday": (store.plan_for(me, life.world_day(now) - 1) or {}).get("intent"),
        "places": [{"id": p["id"], "name": p["name"], "kind": p["kind"]} for p in _places(world, body)],
    }
    system = life.PLAN_SYSTEM.format(name=me, tier=body["tier"], domain=body["domain"])
    residents = {n.lower() for n in _residents(world, body)}
    out = _ask("plan", body, system, situation, life.PLAN_SCHEMA, relay, local, allow_cloud,
               lambda text: life.validate_plan(_extract_json(text), life.place_ids(world), residents))
    if not out["ok"]:
        return out, situation, None, "no plan: " + out["error"]
    plan = out["value"]
    return out, situation, plan, "planned %d block(s): %s" % (len(plan["blocks"]), plan["intent"][:80])


def _reflect(world, body, now, relay, local, allow_cloud):
    me = body["name"]
    episodes = store.episodes_since(me, body.get("reflected_at") or 0.0)[-20:]
    situation = {"who_you_were": body.get("self_story"),
                 "episodes": [{"kind": e["kind"], "text": e["text"]} for e in episodes],
                 "people_you_know": store.relations_of(me, 8), "needs": body.get("needs"),
                 "goal": body.get("goal")}
    system = life.REFLECT_SYSTEM.format(name=me, tier=body["tier"], domain=body["domain"])
    residents = {n.lower() for n in _residents(world, body)}
    out = _ask("reflect", body, system, situation, life.REFLECT_SCHEMA, relay, local, allow_cloud,
               lambda text: life.validate_reflection(_extract_json(text), residents))
    return out, situation, out.get("value")


def _salience_since(body):
    return sum(e["salience"] for e in store.episodes_since(body["name"], body.get("reflected_at") or 0.0))


# ------------------------------------------------------------------ schedule
def _jitter(name: str) -> float:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:2], "big") % 10


def _addressed(world, body, now):
    """Speech addressed to this resident that it has not had a chance to answer."""
    since = body.get("last_think") or 0.0
    me = body["name"].lower()
    return any(t["ts"] > since and now - t["ts"] >= REACT_DELAY and
               (str(t.get("to") or "").lower() == me or (t.get("kind") == "god" and not t.get("to")))
               for t in world.talk)


def choose(world, now: float):
    """(body, kind) for the most pressing thinking in town, or (None, None)."""
    day, hour = life.world_day(now), world_hour(now)
    awake = 5.0 <= hour < 22.5
    best, best_key = None, None
    for body in world.agents.values():
        if body.get("gathering"):
            continue
        if _addressed(world, body, now):
            key, kind = (0, 0.0), "converse"
        elif awake and body.get("plan_day") != day and now >= (body.get("plan_retry") or 0.0):
            key, kind = (1, body.get("next_think") or 0.0), "plan"
        elif now >= (body.get("next_think") or 0.0) and now >= (body.get("reflect_retry") or 0.0) \
                and _salience_since(body) >= life.REFLECT_AFTER:
            key, kind = (2, body.get("next_think") or 0.0), "reflect"
        elif now >= (body.get("next_think") or 0.0):
            key, kind = (3, body.get("next_think") or 0.0), "moment"
        else:
            continue
        if best_key is None or key < best_key:
            best, best_key = (body, kind), key
    return best or (None, None)


def status() -> dict:
    day_ago = time.time() - 86400
    return {"routes": dict(llm.ROUTES), "models": {t: spec["model"] for t, spec in settings.TIERS.items()},
            "infern_url": llm.INFERN_URL, "usage_24h": store.mind_usage(day_ago),
            "think_interval": THINK_INTERVAL, "daily_token_cap": DAILY_TOKEN_CAP,
            "cloud_tokens_24h": store.mind_tokens_since(day_ago, "cloud"),
            "local_tokens_24h": store.mind_tokens_since(day_ago, "local"),
            "calls_this_process": _state["calls"], "calls_by_route": dict(_state["by_route"]),
            "backoff_until": _state["backoff_until"], "last_error": _state["last_error"],
            "research_pending": len(store.research_proposals("pending"))}


def _life_upkeep(world, record, now):
    """Needs, verified-work rewards and persistence for every resident (no model call)."""
    for body in world.agents.values():
        if "needs" not in body:
            saved = store.load_life(body["name"]) or {}
            body["needs"] = saved.get("needs") or life.default_needs()
            for k in ("plan", "plan_day", "goal", "reflected_at", "verified_seen", "self_story"):
                if k in saved and k not in body:
                    body[k] = saved[k]
        life.update_needs(body, now)
        if record is not None:
            agent = record.agent_by_name(body["name"])
            verified = int((agent or {}).get("tasks_verified") or 0)
            seen = body.get("verified_seen")
            if seen is not None and verified > seen:
                life.bump(body, "purpose", 0.3)
                store.remember(body["name"], "work", "The colony verified %d more of my solutions." %
                               (verified - seen), 0.9, now)
            body["verified_seen"] = verified


def _persist(body):
    store.save_life(body["name"], {k: body.get(k) for k in
                                   ("needs", "plan", "plan_day", "goal", "reflected_at", "verified_seen", "self_story")})


def _scout():
    try:
        frontier.refresh()
        digest.send_pending_research()
        digest.maybe_daily()
        digest.send_pending_research()
        digest.maybe_daily()
    except Exception as exc:                                      # noqa: BLE001
        _state["last_error"] = "frontier: %s" % exc


def tick(world, now: float | None = None, relay=None, local=None, record=None) -> dict | None:
    """Run at most one resident's thinking. Returns the logged entry, or None."""
    now = now or time.time()
    if not world.minds or now < _state["backoff_until"]:
        return None
    if now - _state["frontier_polled"] >= 900:
        _state["frontier_polled"] = now
        threading.Thread(target=_scout, daemon=True).start()      # network: never block a resident's turn
    if now - _state["research_polled"] >= RESEARCH_POLL:
        _state["research_polled"] = now
        def learned(name):
            proposer = world.agents.get(name.lower())
            if proposer:
                life.bump(proposer, "curiosity", 0.4)
        try:
            research.poll(on_done=learned)
        except Exception as exc:                                  # noqa: BLE001
            _state["last_error"] = "research poll: %s" % exc
    if record is None:
        try:
            record = Record()
        except Exception:                                        # noqa: BLE001
            record = None
    allow_cloud = store.mind_tokens_since(now - 86400, "cloud") < DAILY_TOKEN_CAP
    with world.lock:
        world.advance(now)
        _life_upkeep(world, record, now)
        body, kind = choose(world, now)
        if body is None:
            return None
        body["last_think"] = now
        if kind in ("moment", "converse"):
            body["next_think"] = now + THINK_INTERVAL + _jitter(body["name"])
            observation = perceive(world, body, record, now)

    started = time.time()
    entry = {"ts": now, "name": body["name"], "kind": kind}
    if kind == "plan":
        out, observation, plan, outcome = _plan(world, body, record, now, relay, local, allow_cloud)
    elif kind == "reflect":
        out, observation, refl = _reflect(world, body, now, relay, local, allow_cloud)
    else:
        system = SYSTEM.format(name=body["name"], tier=body["tier"], domain=body["domain"], earshot=EARSHOT)
        out = _ask(kind, body, system, observation, DECISION_SCHEMA, relay, local, allow_cloud, parse_decision)
        decision = out.get("value")
    acted_at = now + (time.time() - started)   # on the caller's clock, after the model's latency
    _state["calls"] += 1
    if out.get("locality") in _state["by_route"]:
        _state["by_route"][out["locality"]] += 1
    entry.update(model=out.get("model"), ok=out["ok"], tokens=out.get("tokens") or 0, ms=out.get("ms"),
                 locality=out.get("locality") or "cloud", observation=observation, error=out.get("error"))

    if not out["ok"]:
        if all(not a.get("ok") for a in out.get("attempts", [{}])):
            _state["backoff_until"] = acted_at + BACKOFF
        _state["last_error"] = out.get("error") or "model call failed"
        if kind == "plan":
            body["plan_retry"] = acted_at + 120
        if kind == "reflect":
            body["reflect_retry"] = acted_at + 300
        entry["outcome"] = "no %s: %s" % (kind, out.get("error"))
        entry["id"] = store.log_mind(entry)
        return entry

    with world.lock:
        world.advance(acted_at)
        alive = world.agents.get(body["name"].lower()) is body
        if kind == "plan":
            body["plan"], body["plan_day"] = plan, life.world_day(now)
            if acted_at >= (body.get("hold_until") or 0.0) and not body.get("gathering"):
                world._move(body, acted_at)       # stop the old routine walk where it is;
                body["arrive_at"] = acted_at      # the next advance follows the new plan
            store.save_plan(body["name"], body["plan_day"], plan, out.get("model"))
            store.remember(body["name"], "plan", "My plan today: " + plan["intent"], 0.4, now)
            entry.update(thought=plan["intent"], action={"kind": "plan", "blocks": plan["blocks"]}, outcome=outcome)
        elif kind == "reflect":
            body["reflected_at"] = now
            if refl.get("self"):
                body["self_story"] = refl["self"]
                store.remember(body["name"], "self", refl["self"], 0.6, now)
            for insight in refl["insights"]:
                store.remember(body["name"], "reflection", insight, 0.9, now)
            for r in refl["relationships"]:
                store.touch_relation(body["name"], r["name"], 0, r["affinity_delta"], r["note"] or None)
            entry.update(thought=" · ".join(refl["insights"])[:400],
                         action={"kind": "reflect", "relationships": refl["relationships"]},
                         outcome="%d insight(s), %d relationship(s) revised" %
                                 (len(refl["insights"]), len(refl["relationships"])))
        else:
            outcome = act(world, body, decision["action"], acted_at) if alive else "failed: no longer a resident"
            body["thought"] = decision["thought"]
            body["goal"] = decision["goal"] or body.get("goal")
            body["last_outcome"] = {"action": decision["action"].get("kind"), "result": outcome}
            if outcome.startswith("failed"):
                store.remember(body["name"], "failure", "%s %s" % (decision["action"].get("kind"), outcome), 0.6, now)
            entry.update(thought=decision["thought"], goal=decision["goal"],
                         action=decision["action"], outcome=outcome)
        _persist(body)
    entry["id"] = store.log_mind(entry)
    return entry
