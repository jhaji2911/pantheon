"""Pantheon — the world the CIs live in.

This is the cheap layer and it is meant to be cheap. A world (places, a clock, bodies,
habits) advances deterministically off wall-clock time and costs nothing: the CIs walk to
work at dawn, gather at the Agora at dusk, and rest at night whether or not anyone is
looking. Intelligence is a *separate*, metered layer — a CI only reasons (an LLM call)
when a mind is actually needed, and it is off by default so the world can be embodied at
any scale without burning tokens.

Why this beats a physical body: an Arduino robot is one body that costs money and dies on
a desk. A virtual body is a position, a facing, a home and a habit — ten thousand of them
cost a few watts. Embodiment scales when the body is the world, and the mind is metered.

The colony's record (economy, tasks, verifier) remains read-only and remains the truth;
Pantheon is where those CIs get bodies and can be met.
"""
from __future__ import annotations

import json
import math
import pathlib
import threading
import time

import navgrid

WORLD_FILE = pathlib.Path(__file__).resolve().parent / "pantheon.json"

# One full day in real seconds — short enough that you can watch dusk arrive.
DAY_SECONDS = 20 * 60.0
SPEED = 1.4          # world units / second
RUN_SPEED = 3.6      # world units / second when a CI runs
MINDS_ENABLED = False  # the metered layer (minds.py): turned on deliberately, never by default

PLACES = {
    "agora":       dict(name="The Agora",       x=0.0,  z=0.0,   kind="communal",  hue=210),
    "foundry":     dict(name="The Foundry",     x=16.0, z=10.0,  kind="cyber",     hue=142),
    "observatory": dict(name="The Observatory", x=-16.0, z=10.0, kind="orbital",   hue=42),
    "conservatory":dict(name="The Conservatory",x=-16.0, z=-10.0, kind="climate",  hue=176),
    "lattice":     dict(name="The Lattice",     x=16.0, z=-10.0, kind="quantum",   hue=262),
    "study":       dict(name="The Study",       x=0.0,  z=13.0,  kind="brief",     hue=320),
    "hall":        dict(name="The Hall",        x=0.0,  z=-13.0, kind="assembly",  hue=48),
    "archive":     dict(name="The Archive",     x=22.0, z=0.0,   kind="ledger",    hue=200),
}

DOMAIN_HOME = {
    "cyber": "foundry", "orbital": "observatory", "climate": "conservatory",
    "quantum": "lattice", "brief": "study", "world": "study",
}

ACTIVITY = {
    "waking":    "waking",
    "working":   "at work",
    "gathering": "at the Agora",
    "resting":   "resting",
}


def world_hour(now: float) -> float:
    return (now % DAY_SECONDS) / DAY_SECONDS * 24.0


def phase_of(hour: float) -> str:
    if 5 <= hour < 9:
        return "waking"
    if 9 <= hour < 18:
        return "working"
    if 18 <= hour < 21:
        return "gathering"
    return "resting"


def phase_place(phase: str, home: str) -> str:
    if phase == "gathering":
        return "agora"
    if phase == "waking":
        return home if home != "agora" else "study"
    return home  # working and resting both at home



class Pantheon:
    def __init__(self, path: pathlib.Path = WORLD_FILE):
        self.path = path
        self.agents = {}  # name -> body dict
        self.minds = MINDS_ENABLED
        self.talk = []    # recent in-world speech: {name, text, x, z, ts}
        self.dynamic_places = []
        self.artifacts = []
        self.assets = []
        # The brain thread (minds.py) and HTTP handlers both mutate bodies; hold this
        # while advancing, snapshotting or applying a decision. Never across a model call.
        self.lock = threading.RLock()
        self._nav = None
        self._nav_key = None
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        self.agents = data.get("agents", {}) or {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"agents": self.agents}, indent=1))

    def register_agent(self, name: str, tier: str, domain: str):
        key = name.lower()
        if key in self.agents:
            return
        home = DOMAIN_HOME.get(domain, "study")
        p = PLACES[home]
        self.agents[key] = {
            "name": name, "tier": tier, "domain": domain, "home": home,
            "x": p["x"], "z": p["z"], "fx": 0.0, "fz": 1.0,
            "phase": "resting", "place": home, "activity": ACTIVITY["resting"],
            "dest_x": p["x"], "dest_z": p["z"], "depart_at": 0.0, "arrive_at": 0.0,
            "since_x": p["x"], "since_z": p["z"], "next_think": 0.0, "next_wander": 0.0,
        }

    def remove_missing(self, names):
        for key in list(self.agents):
            if self.agents[key]["name"].lower() not in names:
                del self.agents[key]

    # ------------------------------------------------------------------ navigation
    def nav(self) -> navgrid.NavGrid:
        """The walkable grid for the current town; rebuilt only when its geometry changes."""
        key = (tuple(sorted(p["id"] for p in self.dynamic_places)),
               tuple(sorted(str(a["id"]) for a in self.assets)),
               tuple(sorted((b["name"], b["home"]) for b in self.agents.values())))
        if self._nav is None or self._nav_key != key:
            self._nav = navgrid.NavGrid(self.layout())
            self._nav_key = key
        return self._nav

    def layout(self) -> dict:
        return navgrid.layout([dict(v, id=k) for k, v in PLACES.items()], self.dynamic_places, self.assets,
                              [{"name": b["name"], "home": b["home"]} for b in self.agents.values()])

    def houses(self) -> list:
        return self.nav().layout["houses"]

    def house_of(self, name: str) -> dict | None:
        return next((h for h in self.houses() if h["owner"].lower() == name.lower()), None)

    def find_place(self, pid: str) -> dict | None:
        """A civic place, a pavilion, or a resident's house."""
        return (dict(PLACES[pid], id=pid) if pid in PLACES else
                next((d for d in self.dynamic_places if d["id"] == pid), None) or
                next((h for h in self.houses() if h["id"] == pid), None))

    def _journey(self, body: dict, x: float, z: float, now: float, speed: float = SPEED) -> float:
        """Route the body to (x, z) around every wall and object; returns the path length."""
        path = self.nav().route((body["x"], body["z"]), (x, z))
        length = navgrid.path_length(path)
        body["path"] = path
        body["since_x"], body["since_z"] = path[0]
        body["dest_x"], body["dest_z"] = path[-1]
        body["depart_at"] = now
        body["arrive_at"] = now + length / speed
        if length > 0.01:
            (bx, bz), facing = navgrid.point_along(path, 0.0)
            if facing:
                body["fx"], body["fz"] = facing
        return length

    @staticmethod
    def _move(body: dict, now: float) -> None:
        """Place the body where its current journey has it at `now`."""
        path = body.get("path") or [[body["since_x"], body["since_z"]], [body["dest_x"], body["dest_z"]]]
        span = max(0.001, body["arrive_at"] - body["depart_at"])
        t = min(1.0, max(0.0, (now - body["depart_at"]) / span))
        (x, z), facing = navgrid.point_along(path, navgrid.path_length(path) * t)
        body["x"], body["z"] = x, z
        if facing:
            body["fx"], body["fz"] = facing

    def spot(self, name: str, place_id: str, variant: int = 0):
        """A resident's own standing spot inside a place, so bodies do not stack."""
        p = self.find_place(place_id)
        if not p:
            return None
        h = sum(ord(c) * (i + 1) for i, c in enumerate(name)) + variant * 97
        if place_id in PLACES and variant == 0:   # its own desk, if it works here
            desk = next((w for w in self.nav().layout["workstations"]
                         if w["place"] == place_id and w["name"].lower() == name.lower()), None)
            if desk:
                return tuple(desk["chair"])
        if p.get("kind") == "house":              # somewhere in the living room
            return float(p["x"]) + ((h % 7) - 3) * 0.4, float(p["z"]) + ((h % 5) - 2) * 0.4
        if place_id == "agora":   # a ring around the monument
            ang = (h % 360) * math.pi / 180.0
            r = 2.3 + (h % 4) * 0.2
            return p["x"] + math.cos(ang) * r, p["z"] + math.sin(ang) * r
        if place_id in PLACES:    # the open front half of the room, clear of the desks
            return p["x"] + ((h % 53) / 52.0 - 0.5) * 5.2, p["z"] + 0.3 + (h % 11) / 10.0 * 2.0
        ang = (h % 360) * math.pi / 180.0
        return float(p["x"]) + math.cos(ang) * 2.0, float(p["z"]) + math.sin(ang) * 2.0

    def begin_gathering(self, names, meeting_id: str, now: float, hold_seconds: float = 900.0):
        """Move selected residents to assigned seats around the Hall table."""
        chosen = [self.agents[name.lower()] for name in names if name.lower() in self.agents]
        count = max(1, len(chosen))
        hall = PLACES["hall"]
        for index, body in enumerate(chosen):
            angle = (2.0 * math.pi * index / count) - math.pi / 2.0
            x = hall["x"] + math.cos(angle) * 2.25
            z = hall["z"] + math.sin(angle) * 2.25
            body["gathering"] = {"id": meeting_id, "x": x, "z": z, "until": now + hold_seconds}
            self._journey(body, x, z, now)
            body["place"] = "hall"
            body["activity"] = "walking to the Hall"
        return [body["name"] for body in chosen]

    def end_gathering(self, meeting_id: str, now: float):
        for body in self.agents.values():
            gathering = body.get("gathering")
            if gathering and gathering.get("id") == meeting_id:
                body.pop("gathering", None)
                body["phase"] = "after_gathering"
                body["arrive_at"] = now
                body["activity"] = "leaving the Hall"

    def record_speech(self, name: str, text: str, now: float | None = None, kind: str = "conversation",
                      to: str | None = None):
        body = self.agents.get(name.lower())
        if not body or not text:
            return
        self.talk.append({"name": body["name"], "text": str(text)[:500], "kind": kind, "to": to,
                          "x": round(body["x"], 2), "z": round(body["z"], 2),
                          "ts": time.time() if now is None else now})
        self.talk = self.talk[-40:]

    def divine(self, creator: str, text: str, now: float, to: str | None = None):
        """The creator's voice: heard by every resident (or only `to`) wherever it stands."""
        self.talk.append({"name": creator, "text": str(text)[:500], "kind": "god", "to": to,
                          "x": None, "z": None, "ts": now})
        self.talk = self.talk[-40:]

    def direct(self, name: str, x: float, z: float, place: str, label: str, now: float,
               run: bool = False, hold: float = 0.0) -> float:
        """Start a routed journey to (x, z); returns the walked distance. `hold` keeps the
        daily routine from overriding a mind's choice for that many seconds after arrival."""
        body = self.agents[name.lower()]
        self._move(body, now)
        dist = self._journey(body, x, z, now, RUN_SPEED if run else SPEED)
        body["place"] = place
        body["activity"] = label
        if hold:
            body["hold_until"] = body["arrive_at"] + hold
        return dist

    # ------------------------------------------------------------------ motion
    def advance(self, now: float):
        hour = world_hour(now)
        phase = phase_of(hour)
        for body in self.agents.values():
            gathering = body.get("gathering")
            if gathering and now < gathering.get("until", now):
                self._move(body, now)
                if now < body["arrive_at"]:
                    body["activity"] = "walking to the Hall"
                else:
                    body["place"], body["activity"] = "hall", "sitting in a CI gathering"
                    dx, dz = PLACES["hall"]["x"] - body["x"], PLACES["hall"]["z"] - body["z"]
                    d = max(0.001, math.hypot(dx, dz))
                    body["fx"], body["fz"] = dx / d, dz / d
                continue
            if gathering:
                body.pop("gathering", None)
                body["phase"] = "after_gathering"
                body["arrive_at"] = now
            # complete any journey first
            self._move(body, now)
            if now < body["arrive_at"]:
                continue
            target, doing = self.desired(body, now, hour, phase)
            if body["activity"].startswith("walking to") or body["activity"] == "leaving the Hall":
                # arrived: say what it is doing here, not where it was going
                body["activity"] = doing if body["place"] == target else \
                    "at " + self.place_name(body["place"])
            if now < (body.get("hold_until") or 0.0):
                continue
            body["phase"] = phase
            if body["place"] != target:
                body["place"] = target
                x, z = self.spot(body["name"], target)
                if self._journey(body, x, z, now) > 0.3:
                    body["activity"] = "walking to " + self.place_name(target)
                else:
                    body["activity"] = doing
                    body["arrive_at"] = now
                continue
            body["activity"] = doing if body["activity"] in ("walking", "") or \
                body["activity"].startswith("at ") else body["activity"]

            # move about the room so the CIs are visibly alive
            if target == body["home"] and now >= (body.get("next_wander") or 0.0):
                body["next_wander"] = now + 14.0
                body["wander"] = 1 - int(body.get("wander") or 0)
                x, z = self.spot(body["name"], body["home"], body["wander"])
                self._journey(body, x, z, now, SPEED * 0.6)
                body["activity"] = "walking"
            elif body["activity"] == "walking":
                body["activity"] = doing

    def place_name(self, pid: str) -> str:
        p = self.find_place(pid)
        return p["name"] if p else pid

    def desired(self, body: dict, now: float, hour: float, phase: str):
        """(place, activity) the resident should be at now: its own plan for today when it
        has one (life.py writes it), otherwise the default routine for the phase."""
        plan = body.get("plan")
        if plan and body.get("plan_day") == int(now // DAY_SECONDS):
            for block in plan.get("blocks", ()):
                if block["from"] <= hour < block["to"] and self.find_place(block["place"]):
                    return block["place"], block["doing"]
        if phase == "resting":                    # nights are spent at home
            house = self.house_of(body["name"])
            if house:
                return house["id"], "at home"
        return phase_place(phase, body["home"]), ACTIVITY[phase]

    def set_minds(self, on: bool) -> None:
        self.minds = bool(on)

    # ------------------------------------------------------------------ view
    def snapshot(self, now: float):
        hour = world_hour(now)
        phase = phase_of(hour)
        bodies = []
        for b in self.agents.values():
            bodies.append({
                "name": b["name"], "tier": b["tier"], "domain": b["domain"],
                "home": b["home"], "place": b["place"], "activity": b["activity"],
                "profile": b.get("profile"), "role": b.get("role"),
                "gathering": bool(b.get("gathering")),
                "x": round(b["x"], 2), "z": round(b["z"], 2),
                "fx": round(b["fx"], 3), "fz": round(b["fz"], 3),
                "goal": b.get("goal"), "thought": b.get("thought"), "needs": b.get("needs"),
                "self_story": b.get("self_story"),
                "plan_intent": (b.get("plan") or {}).get("intent") if b.get("plan_day") == int(now // DAY_SECONDS) else None,
                "path": b.get("path") if now < b["arrive_at"] else None,
                "depart_at": round(b["depart_at"], 3), "arrive_at": round(b["arrive_at"], 3),
            })
        return {
            "layout": self.nav().layout,
            "clock": {
                "now": now, "hour": round(hour, 2), "phase": phase,
                "minutes_per_day": DAY_SECONDS / 60.0,
            },
            "places": [dict(v, id=k) for k, v in PLACES.items()] + list(self.dynamic_places),
            "agents": bodies,
            "artifacts": list(self.artifacts),
            "assets": list(self.assets),
            "minds": self.minds,
            "talk": list(self.talk),
        }


_world = None


def get_world() -> Pantheon:
    global _world
    if _world is None:
        _world = Pantheon()
    return _world
