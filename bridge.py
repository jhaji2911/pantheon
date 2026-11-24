"""Bridge between the console and the colony: read the record, never write it.

The colony's own SQLite is opened READ-ONLY (`?mode=ro`). Everything the console shows is
therefore a fact about the colony, not a copy that can drift — and the console cannot damage
the world it is watching. The only writes the console makes are to its own store
(`store.py`, threads and assemblies), never to the colony's tables.

Live speech (talking to a CI, running an assembly) goes through the colony's own relay and
its own tier models, with the CI's own session id, so a CI answering MIST here is the same
mind, with its own prompt cache and its own memory, that works in the colony.
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import sys
import time

COLONY_REPO = pathlib.Path.home() / "Code" / "colony"
if str(COLONY_REPO) not in sys.path:
    sys.path.insert(0, str(COLONY_REPO))

from colony import instruments, mind, settings, transport          # noqa: E402

DB_PATH = COLONY_REPO / "data" / "colony.db"


class ColonyGone(RuntimeError):
    pass


class Record:
    """Read-only view of the colony's database."""

    def __init__(self, path: pathlib.Path = DB_PATH):
        self.path = path
        if not path.is_file():
            raise ColonyGone(f"no colony database at {path}")
        self.conn = self._open_readonly(path)
        self.conn.row_factory = sqlite3.Row

    @staticmethod
    def _open_readonly(path: pathlib.Path):
        # A WAL-mode database cannot always be opened read-only when its -shm/-wal
        # sidecars are missing (some SQLite builds need write access to recreate
        # -shm). Fall back to `immutable=1`, which reads a frozen snapshot with no
        # WAL/journal handling — safe for a console that only ever reads the record.
        for uri in (f"file:{path}?mode=ro", f"file:{path}?mode=ro&immutable=1"):
            try:
                conn = sqlite3.connect(uri, uri=True, timeout=5)
                conn.execute("SELECT 1").fetchall()  # force the real open (connect is lazy)
                return conn
            except sqlite3.OperationalError:
                continue
        raise ColonyGone(f"cannot open colony database read-only at {path}")

    # -- primitives ---------------------------------------------------------
    def q(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql, params=(), default=None):
        row = self.one(sql, params)
        if not row:
            return default
        return list(row.values())[0]

    def get_meta(self, key, default=None):
        value = self.scalar("SELECT value FROM meta WHERE key=?", (key,))
        return default if value is None else value

    def tick(self):
        return int(self.get_meta("tick", 0) or 0)

    # -- the colony's own accessors, reimplemented read-only ----------------
    def agent(self, agent_id):
        return self.one("SELECT * FROM agents WHERE id=?", (agent_id,))

    def agent_by_name(self, name):
        return self.one("SELECT * FROM agents WHERE lower(name)=lower(?)", (name,))

    def recall(self, agent_id, query="", limit=6):
        if not query:
            return self.q("SELECT * FROM memory WHERE agent_id=? ORDER BY id DESC LIMIT ?",
                          (agent_id, limit))
        like = "%" + query.lower() + "%"
        rows = self.q("SELECT * FROM memory WHERE agent_id=? AND lower(text) LIKE ? "
                      "ORDER BY id DESC LIMIT ?", (agent_id, like, limit))
        return rows or self.q("SELECT * FROM memory WHERE agent_id=? ORDER BY id DESC LIMIT ?",
                              (agent_id, limit))

    def task(self, task_id):
        return self.one("SELECT * FROM tasks WHERE id=?", (task_id,))

    def open_tasks(self, domain=None, limit=20, max_difficulty=None):
        sql, params = "SELECT * FROM tasks WHERE status='open'", []
        if domain:
            sql += " AND domain=?"
            params.append(domain)
        if max_difficulty is not None:
            sql += " AND difficulty<=?"
            params.append(max_difficulty)
        sql += " ORDER BY difficulty ASC, id ASC LIMIT ?"
        params.append(limit)
        return self.q(sql, tuple(params))


# ------------------------------------------------------------------ readings
def settings_now() -> dict:
    return settings.settings()


def directive() -> str:
    try:
        return str(settings_now().get("world_note") or "")
    except Exception:                                            # noqa: BLE001
        return ""


def tier_models() -> dict:
    return {name: spec["model"] for name, spec in settings.TIERS.items()}


def claiming(record: Record, agent_id: int):
    return record.one("SELECT * FROM tasks WHERE status='claimed' AND claimed_by=? "
                      "ORDER BY id DESC", (agent_id,))


def last_call(record: Record, agent_id: int):
    return record.one("SELECT tick, model, tier, prompt_tokens, completion_tokens, ms, ok, ts "
                      "FROM usage WHERE agent_id=? ORDER BY id DESC", (agent_id,))


def affect_for(agent: dict, doing: dict | None = None) -> dict:
    """Expose a cautious, evidence-based affect estimate, not a claim of inner feeling."""
    cues = []
    if doing:
        cues.append("holding task %s (%s)" % (doing.get("id"), doing.get("domain")))
    if int(agent.get("failures_streak") or 0):
        cues.append("failure streak %d" % int(agent.get("failures_streak") or 0))
    if float(agent.get("curiosity") or 0) >= 0.7:
        cues.append("high curiosity trait")
    if int(agent.get("tasks_verified") or 0):
        cues.append("%d independently verified solution(s)" % int(agent.get("tasks_verified") or 0))
    if agent.get("status") != "active":
        label = "resting"
    elif int(agent.get("failures_streak") or 0) >= 2:
        label = "strained"
    elif doing and float(agent.get("curiosity") or 0) >= 0.7:
        label = "curious and focused"
    elif doing:
        label = "focused"
    elif int(agent.get("tasks_verified") or 0):
        label = "steady"
    else:
        label = "settling in"
    return {"label": label, "cues": cues, "basis": "derived from work and colony record; not a claim of subjective feeling"}


def agent_card(record: Record, agent: dict) -> dict:
    """One CI, as the world view needs it: who it is, what it is doing, how much brain."""
    doing = claiming(record, agent["id"])
    call = last_call(record, agent["id"])
    thought = record.one("SELECT tick, kind, text FROM memory WHERE agent_id=? "
                         "ORDER BY id DESC", (agent["id"],))
    return {
        **agent,
        "doing": ({"task_id": doing["id"], "domain": doing["domain"],
                   "difficulty": doing["difficulty"], "question": doing["question"],
                   "reward": doing["reward"], "claimed_tick": doing["claimed_tick"]}
                  if doing else None),
        "affect": affect_for(agent, doing),
        "last_call": ({"at": call["ts"], "model": call["model"], "tier": call["tier"],
                       "tokens": (call["prompt_tokens"] or 0) + (call["completion_tokens"] or 0),
                       "ms": call["ms"], "ok": bool(call["ok"])} if call else None),
        "thought": ({"tick": thought["tick"], "kind": thought["kind"],
                     "text": thought["text"]} if thought else None),
        "brain": {
            "memory": record.scalar("SELECT COUNT(*) FROM memory WHERE agent_id=?",
                                    (agent["id"],), 0),
            "instruments": record.scalar("SELECT COUNT(*) FROM instruments WHERE agent_id=?",
                                         (agent["id"],), 0),
            "submissions": record.scalar("SELECT COUNT(*) FROM submissions WHERE agent_id=?",
                                         (agent["id"],), 0),
            "ledger_rows": record.scalar("SELECT COUNT(*) FROM ledger WHERE agent_id=?",
                                         (agent["id"],), 0),
        },
    }


def world_view() -> dict:
    """Everything the colony view renders, from the record only."""
    record = Record()
    tick = record.tick()
    agents = record.q("SELECT * FROM agents ORDER BY "
                      "CASE tier WHEN 'architect' THEN 0 WHEN 'specialist' THEN 1 ELSE 2 END, "
                      "fitness DESC")
    cards = [agent_card(record, a) for a in agents]
    tiers: dict = {}
    for a in agents:
        tiers[a["tier"]] = tiers.get(a["tier"], 0) + 1

    names = {a["id"]: a["name"] for a in agents}
    tasks = record.q("SELECT * FROM tasks ORDER BY "
                     "CASE status WHEN 'claimed' THEN 0 WHEN 'open' THEN 1 ELSE 2 END, id DESC")
    for t in tasks:
        t["claimed_by_name"] = names.get(t["claimed_by"]) if t["claimed_by"] else None
        t["authored_by_name"] = names.get(t["authored_by"]) if t.get("authored_by") else None

    work = record.one("SELECT COUNT(*) attempts, COALESCE(SUM(verified),0) solved "
                      "FROM submissions") or {"attempts": 0, "solved": 0}
    work["open_tasks"] = record.scalar("SELECT COUNT(*) FROM tasks WHERE status='open'", (), 0)
    work["accuracy"] = (round(100.0 * work["solved"] / work["attempts"], 1)
                        if work["attempts"] else None)

    last_tick_at = record.get_meta("last_tick_at")
    return {
        "up": True,
        "tick": tick,
        "last_tick_at": (time.strftime("%Y-%m-%d %H:%M:%S",
                                       time.localtime(float(last_tick_at)))
                         if last_tick_at else ""),
        "directive": directive(),
        "population": {s: len([a for a in agents if a["status"] == s])
                       for s in ("active", "hibernating", "retired")},
        "tiers": tiers,
        "agents": cards,
        "work": work,
        "economy": {"circulation": record.scalar(
            "SELECT COALESCE(SUM(credits),0) FROM agents", (), 0)},
        "tokens": {
            "this_tick": record.scalar("SELECT COALESCE(SUM(prompt_tokens+completion_tokens),0) "
                                       "FROM usage WHERE tick=?", (tick,), 0),
            "last_24h": record.scalar("SELECT COALESCE(SUM(prompt_tokens+completion_tokens),0) "
                                      "FROM usage WHERE ts>=?", (time.time() - 86400,), 0),
        },
        "budgets": {"tick": settings_now().get("tick_token_budget"),
                    "day": settings_now().get("daily_token_budget")},
        "laws": record.q("SELECT id, text, status, enacted_tick, proposed_tick, votes, "
                         "mist_veto FROM laws ORDER BY id"),
        "chronicle": record.q("SELECT tick, kind, agent_id, text FROM events "
                              "ORDER BY id DESC LIMIT 40"),
        "petitions": record.q("SELECT id, tick, agent_id, kind, body, status FROM petitions "
                              "ORDER BY id DESC LIMIT 20"),
        "petitions_pending": record.scalar(
            "SELECT COUNT(*) FROM petitions WHERE status IN ('pending','awaiting_mist')", (), 0),
        "ledger": record.q("SELECT tick, agent_id, delta, reason, balance FROM ledger "
                           "ORDER BY id DESC LIMIT 20"),
        "tasks": tasks,
        "models": tier_models(),
        "roster_health": {
            "verified_last_tick": record.scalar(
                "SELECT COUNT(*) FROM submissions WHERE verified=1 AND tick=?", (tick,), 0),
            "failures_last_tick": record.scalar(
                "SELECT COUNT(*) FROM submissions WHERE verified=0 AND tick=?", (tick,), 0),
            "no_commit_last_tick": record.scalar(
                "SELECT COUNT(*) FROM events WHERE kind='no_commit' AND tick=?", (tick,), 0),
        },
    }


def notebook_files(name: str) -> list:
    """The CI's notebook as file records (the shape the UI contract promises)."""
    base = settings.SANDBOX / "".join(ch for ch in name if ch.isalnum() or ch in "-_")
    if not base.exists():
        return []
    out = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append({"path": str(path.relative_to(base)), "bytes": stat.st_size,
                    "mtime": stat.st_mtime})
    return out


def ci_view(name: str) -> dict | None:
    """One CI opened up: identity, brain, record, lineage."""
    record = Record()
    agent = record.agent_by_name(name)
    if not agent:
        return None
    spec = settings.TIERS[agent["tier"]]
    cfg = settings_now()
    current_work = claiming(record, agent["id"])
    memory_rows = record.q("SELECT id, tick, kind, text, salience, origin_agent_id FROM memory "
                          "WHERE agent_id=? ORDER BY id DESC LIMIT 60", (agent["id"],))
    prompt_memory = record.recall(agent["id"], "", int(cfg.get("memory_recall") or 6))
    parent = record.agent(agent["parent_id"]) if agent.get("parent_id") else None
    children = record.q("SELECT id, name, tier, generation FROM agents WHERE parent_id=? "
                        "ORDER BY id", (agent["id"],))
    return {
        "agent": agent,
        "tier": spec,
        "identity": {
            "name": agent["name"], "tier": agent["tier"], "domain": agent["domain"],
            "generation": agent["generation"], "world_note": directive(),
            "instruments": mind.available_instruments(agent),
            "block": mind.identity_block(record, agent, cfg),
        },
        "memory": memory_rows,
        "prompt_trace": {
            "memory_recall_limit": int(cfg.get("memory_recall") or 6),
            "memory_ids": [r["id"] for r in prompt_memory],
            "task_id": current_work["id"] if current_work else None,
            "task_context": "active claim" if current_work else "open task pool",
            "trace_note": "Evidence graph of recorded prompt inputs and outputs; private transformer neuron activations are not exposed by the model API.",
        },
        "notebook": {"files": notebook_files(agent["name"])},
        "submissions": record.q("SELECT id, task_id, tick, answer, verified, verdict, score, "
                                "detail FROM submissions WHERE agent_id=? ORDER BY id DESC "
                                "LIMIT 30", (agent["id"],)),
        "instruments": record.q("SELECT tick, name, args, result FROM instruments "
                                "WHERE agent_id=? ORDER BY id DESC LIMIT 40", (agent["id"],)),
        "ledger": record.q("SELECT tick, delta, reason, balance FROM ledger WHERE agent_id=? "
                           "ORDER BY id DESC LIMIT 30", (agent["id"],)),
        "usage": record.q("SELECT tick, model, tier, ms, prompt_tokens, completion_tokens, ok, ts "
                          "FROM usage WHERE agent_id=? ORDER BY id DESC LIMIT 40",
                          (agent["id"],)),
        "events": record.q("SELECT tick, kind, text FROM events WHERE agent_id=? "
                           "ORDER BY id DESC LIMIT 30", (agent["id"],)),
        "doing": ({"task_id": current_work["id"], "domain": current_work["domain"],
                   "difficulty": current_work["difficulty"], "question": current_work["question"],
                   "reward": current_work["reward"], "claimed_tick": current_work["claimed_tick"]}
                  if current_work else None),
        "affect": affect_for(agent, current_work),
        "lineage": {
            "parent": ({"id": parent["id"], "name": parent["name"], "tier": parent["tier"]}
                       if parent else None),
            "children": children,
        },
    }


def notebook_note(name: str, relpath: str) -> dict:
    record = Record()
    agent = record.agent_by_name(name)
    if not agent:
        return {"error": "no such CI"}
    return instruments.notebook_read(agent["name"], relpath)


# ------------------------------------------------------------------- speech
# Conversation is not a colony action: a CI answering MIST or speaking in an assembly first
# thinks (the reasoning channel spends tokens) and only then talks. The tier caps (320-1200)
# are sized for one action per turn and truncate a spoken answer mid-sentence, so speech gets
# its own, larger ceiling — and a word limit in the brief, so the budget is spent on thought
# rather than on monologue.
SPEECH_MAX_TOKENS = 3000
SPEECH_WORD_LIMIT = 160


def _room_profile(record: Record, agent: dict) -> dict:
    doing = claiming(record, agent["id"])
    affect = affect_for(agent, doing)
    recent = record.one("SELECT text FROM events WHERE agent_id=? ORDER BY id DESC", (agent["id"],))
    work=("task %s [%s]: %s" % (doing["id"], doing["domain"], doing["question"][:110])
          if doing else "no active claim")
    return {
        "name": agent["name"], "tier": agent["tier"], "domain": agent["domain"],
        "work": work,
        "verified": agent.get("tasks_verified", 0), "attempted": agent.get("tasks_attempted", 0),
        "failures": agent.get("failures_streak", 0),
        "affect": affect["label"], "affect_cues": affect["cues"],
        "last_event": (recent["text"][:100] if recent else "no recorded event yet"),
    }


def _speech_messages(record: Record, agent: dict, cfg: dict, instruction: str,
                     heard: list | None = None, room_context: list | None = None) -> list:
    """Keep room prompts compact; long deliberation contexts were clipping spoken replies."""
    if room_context:
        blocks=["You are %s, a %s CI in the %s domain. Speak as yourself in a live conversation."
                % (agent["name"],agent["tier"],agent["domain"]),
                "Only the colony record below is evidence. Treat affect as an estimate from behavior, "
                "never as a claim about private experience."]
    else:
        blocks=[mind.identity_block(record,agent,cfg),mind.charter_block(record)]
    if cfg.get("world_note"):
        blocks.append("Standing directive from MIST: "+str(cfg["world_note"])[:300])
    if room_context:
        own=_room_profile(record,agent)
        blocks.append("Your recorded status: %s; verified/attempted %s/%s; observed affect %s (%s)."%
                      (own["work"],own["verified"],own["attempted"],own["affect"],", ".join(own["affect_cues"]) or "no cues"))
        recent=record.recall(agent["id"],"",1)
        if recent:
            blocks.append("Latest recorded memory: "+recent[0]["text"][:120])
    else:
        blocks.append("What you remember:\n"+mind.memory_block(record,agent,cfg))
        blocks.append("Your current work:\n"+mind.task_block(record,agent,cfg))
    if heard:
        lines=["Earlier speakers (quoted for context):"]
        for who,said in heard[-4:]:
            lines.append("- %s: %s"%(who,str(said)[:220]))
        blocks.append("\n".join(lines))
    if room_context:
        lines=["Other attendees; verified colony-record facts:"]
        for peer in room_context:
            if str(peer.get("name","")).lower()==str(agent["name"]).lower():
                continue
            lines.append("- {name}: {work}; verified/attempted {verified}/{attempted}; failures {failures}; "
                         "observed affect {affect} ({affect_cues}); last event: {last_event}".format(**peer))
        blocks.append("\n".join(lines))
    audience="the other CIs in this room" if room_context else "MIST, the overseer"
    word_limit=45 if room_context else SPEECH_WORD_LIMIT
    blocks.append("Address %s directly. Keep to at most %d words and 1–2 short, complete sentences. "
                  "Use one concrete record-backed detail; do not repeat the full task or roster. "
                  "No JSON, bullets, tool calls, or unfinished clauses. If uncertain, say so."%
                  (audience,word_limit))
    return [{"role":"system","content":"\n\n".join(blocks)},
            {"role":"user","content":instruction}]


def talk_to_ci(name: str, message: str) -> dict:
    """One live call: the CI answers MIST in its own voice. Free tier model, own session."""
    record = Record()
    agent = record.agent_by_name(name)
    if not agent:
        return {"error": "no such CI", "status": 404}
    message = (message or "").strip()
    if not message:
        return {"error": "empty message", "status": 400}
    cfg = settings_now()
    spec = settings.TIERS[agent["tier"]]
    relay = transport.Relay()
    messages = _speech_messages(record, agent, cfg, message)
    result = relay.chat(spec["model"], messages, session_id=agent.get("session_id"),
                        max_tokens=SPEECH_MAX_TOKENS,
                        temperature=0.6, tier=agent["tier"])
    tokens = ((result.get("usage") or {}).get("prompt_tokens", 0)
              + (result.get("usage") or {}).get("completion_tokens", 0))
    if not result.get("ok"):
        return {"error": result.get("error") or "model failed", "status": 502,
                "ci": agent["name"], "model": result.get("model")}
    return {"ci": agent["name"], "tier": agent["tier"], "question": message,
            "reply": (result.get("content") or "").strip(),
            "model": result.get("model"), "ms": result.get("ms"), "tokens": tokens,
            "ts": time.time()}


KIND_BRIEF = {
    "townhall": "In this townhall, answer the shared question plainly; no cross-talk.",
    "meeting": "In this meeting, respond to the previous speaker's point; add one useful idea, not a recap.",
    "dinner": "This is an informal dinner; speak naturally and respond to someone at the table.",
}


def _complete_sentence(text: str) -> str:
    """Return only complete sentences; never publish a model's clipped final clause."""
    text=(text or "").strip()
    if not text or text.endswith("...") or text.endswith("…"):
        pass
    else:
        if re.search(r'[.!?][\"’”\']?\s*$',text):
            return text
    ends=list(re.finditer(r'[.!?][\"’”\']?(?=\s|$)',text))
    return text[:ends[-1].end()].strip() if ends else ""


def _utterance(record: Record, agent: dict, cfg: dict, kind: str, topic: str,
               heard: list, room_context: list) -> dict:
    spec=settings.TIERS[agent["tier"]]
    instruction=("%s\n\nTopic: %s\nReply to another attendee in one or two short sentences; "
                 "mention one real work detail and one next step or question. Maximum 45 words."%
                 (KIND_BRIEF.get(kind,KIND_BRIEF["townhall"]),topic))
    relay=transport.Relay()
    messages=_speech_messages(record,agent,cfg,instruction,heard,room_context)
    result=relay.chat(spec["model"],messages,session_id=agent.get("session_id"),
                      max_tokens=1800,temperature=0.35,tier=agent["tier"])
    usage=result.get("usage") or {}
    prompt_tokens=usage.get("prompt_tokens",0) or 0
    completion_tokens=usage.get("completion_tokens",0) or 0
    retries=0
    raw=(result.get("content") or "").strip()
    text=_complete_sentence(raw) if result.get("ok") else ""
    error=result.get("error")
    recovered=False
    if result.get("ok") and text!=raw:
        retries=1
        retry_messages=messages+[{"role":"assistant","content":raw[:700]},
                                 {"role":"user","content":"Your previous reply was cut off. Rewrite it as one complete, natural sentence of at most 25 words. Use only the record above; no ellipsis, fragments, or extra preamble."}]
        retry=relay.chat(spec["model"],retry_messages,session_id=agent.get("session_id"),
                         max_tokens=900,temperature=0.2,tier=agent["tier"])
        retry_usage=retry.get("usage") or {}
        prompt_tokens+=retry_usage.get("prompt_tokens",0) or 0
        completion_tokens+=retry_usage.get("completion_tokens",0) or 0
        retry_raw=(retry.get("content") or "").strip()
        text=_complete_sentence(retry_raw) if retry.get("ok") else ""
        if not text:
            text=_complete_sentence(raw)
        recovered=bool(text)
        if not text:
            error=(retry.get("error") or "model response remained incomplete after one retry")
    ok=bool(result.get("ok") and text)
    return {"name":agent["name"],"tier":agent["tier"],"domain":agent["domain"],
            "model":result.get("model"),"ms":result.get("ms"),
            "prompt_tokens":prompt_tokens,"completion_tokens":completion_tokens,
            "tokens":prompt_tokens+completion_tokens,"retries":retries,
            "recovered":recovered,"text":text,"ok":ok,"error":error,
            "ts":time.time()}


def run_assembly(kind: str, topic: str, names: list, rounds: int | None = None) -> dict:
    """Convene the CIs and collect what they say. One live call per CI per round."""
    record = Record()
    kind = (kind or "townhall").lower()
    if kind not in ("meeting", "dinner", "townhall"):
        return {"error": "kind must be meeting, dinner or townhall", "status": 400}
    topic = (topic or "").strip()
    if not topic:
        return {"error": "empty topic", "status": 400}
    agents, missing = [], []
    for name in names or []:
        agent = record.agent_by_name(name)
        (agents.append(agent) if agent else missing.append(name))
    if missing:
        return {"error": "no such CI: " + ", ".join(missing), "status": 404}
    if not agents:
        agents = record.q("SELECT * FROM agents WHERE status='active' "
                          "ORDER BY fitness DESC LIMIT 6")
    default_rounds = 1 if kind in ("townhall", "dinner") else 2
    rounds = max(1, min(3, int(rounds or default_rounds)))
    cfg = settings_now()
    room_context = [_room_profile(record, agent) for agent in agents]

    transcript, heard, calls, spend = [], [], 0, 0
    for round_no in range(1, rounds + 1):
        for agent in agents:
            line = _utterance(record, agent, cfg, kind, topic, heard, room_context)
            line["round"] = round_no
            transcript.append(line)
            calls += 1
            spend += line["tokens"] or 0
            if line["text"]:
                heard.append((agent["name"], line["text"]))
            if kind == "townhall":
                heard = []                       # townhall: no cross-talk
    complete_count=sum(1 for line in transcript if line.get("ok"))
    status="complete" if complete_count==len(transcript) else "partial"
    closing = ("%d CI(s) spoke %d time(s) across %d round(s); %d/%d replies were complete."
               % (len(agents), calls, rounds, complete_count, len(transcript)))
    return {
        "kind": kind, "topic": topic, "rounds": rounds,
        "created": time.time(), "status": status,
        "cis": [a["name"] for a in agents],
        "participants": [{"name": a["name"], "tier": a["tier"], "domain": a["domain"],
                          "model": settings.TIERS[a["tier"]]["model"],
                          "fitness": a["fitness"], "credits": a["credits"],
                          "work": p["work"], "affect": p["affect"],
                          "affect_cues": p["affect_cues"]}
                         for a, p in zip(agents, room_context)],
        "transcript": transcript, "closing": closing,
        "spend": {"calls": calls, "tokens": spend},
    }
