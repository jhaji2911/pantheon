"""Seeds the demo colony on first run: six founders, open work, a charter and some history.

The residents' lives in the town (plans, moments, conversations, reflections) are generated
live by your model; this record only gives them a past to start from.
"""
from __future__ import annotations

import json
import sqlite3
import time

from . import settings

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, parent_id INTEGER,
    generation INTEGER NOT NULL DEFAULT 0, tier TEXT NOT NULL DEFAULT 'worker',
    domain TEXT NOT NULL DEFAULT 'quantum', cadence INTEGER NOT NULL DEFAULT 1,
    phase INTEGER NOT NULL DEFAULT 0, credits REAL NOT NULL DEFAULT 0,
    fitness REAL NOT NULL DEFAULT 0, tasks_attempted INTEGER NOT NULL DEFAULT 0,
    tasks_verified INTEGER NOT NULL DEFAULT 0, failures_streak INTEGER NOT NULL DEFAULT 0,
    temperature REAL NOT NULL DEFAULT 0.6, curiosity REAL NOT NULL DEFAULT 0.5,
    session_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', hibernating_since INTEGER,
    born_tick INTEGER NOT NULL, last_tick INTEGER, died_tick INTEGER,
    traits TEXT NOT NULL DEFAULT '{}', world_note TEXT DEFAULT '', epitaph TEXT);
CREATE TABLE memory (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER NOT NULL,
    tick INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
    salience REAL NOT NULL DEFAULT 1.0, origin_agent_id INTEGER);
CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL,
    difficulty INTEGER NOT NULL, question TEXT NOT NULL, spec TEXT NOT NULL,
    check_spec TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_tick INTEGER NOT NULL,
    claimed_by INTEGER, claimed_tick INTEGER, solved_tick INTEGER, reward REAL NOT NULL DEFAULT 0,
    authored_by INTEGER, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
    agent_id INTEGER NOT NULL, tick INTEGER NOT NULL, answer TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0, score REAL NOT NULL DEFAULT 0, detail TEXT, verdict TEXT);
CREATE TABLE ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL,
    agent_id INTEGER, delta REAL NOT NULL, reason TEXT NOT NULL, balance REAL);
CREATE TABLE usage (id INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL, agent_id INTEGER,
    model TEXT, tier TEXT, prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0, ms INTEGER NOT NULL DEFAULT 0,
    ts REAL NOT NULL DEFAULT 0, ok INTEGER NOT NULL DEFAULT 1, error TEXT);
CREATE TABLE laws (id INTEGER PRIMARY KEY AUTOINCREMENT, enacted_tick INTEGER,
    proposed_tick INTEGER NOT NULL, proposed_by INTEGER, text TEXT NOT NULL,
    machine TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'proposed',
    votes TEXT NOT NULL DEFAULT '{}', mist_veto INTEGER NOT NULL DEFAULT 0, decided_tick INTEGER);
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL,
    kind TEXT NOT NULL, agent_id INTEGER, text TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}');
CREATE TABLE instruments (id INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL,
    agent_id INTEGER, name TEXT NOT NULL, args TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE petitions (id INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL,
    agent_id INTEGER, kind TEXT NOT NULL, body TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending', decided_tick INTEGER, decided_by TEXT);
"""

TICK = 24

# name, tier, domain, credits, fitness, attempted, verified, curiosity, first memories
FOUNDERS = [
    ("Fathom", "architect", "climate", 314, 7.0, 29, 11, 0.75, [
        "Ocean heat uptake is the slow variable; surface records lag it by decades.",
        "I spent a whole action thinking and never committed. Next time: one compute, then submit."]),
    ("Kestrel", "architect", "orbital", 91, 2.89, 22, 9, 0.43, [
        "A transfer orbit is a compromise between time and fuel; there is no free lunch.",
        "Need to claim work before I describe it."]),
    ("Vesper", "architect", "quantum", 393, 1.34, 23, 14, 0.54, [
        "Decoherence time sets the budget for every gate I plan.",
        "Tessellate checks my numbers faster than I do. Worth asking first."]),
    ("Morrow", "architect", "cyber", 236, 1.16, 10, 6, 0.70, [
        "A seed mismatch failed task 51. Recompute from the stated seed before answering.",
        "Do not repeat a route that failed without changing something."]),
    ("Tessellate", "architect", "world", 242, 1.01, 6, 3, 0.85, [
        "Every claim gets recomputed before it is believed, including my own.",
        "The town's highway loop is the longest walk; plan around it."]),
    ("Aster", "worker", "quantum", 192, 0.94, 3, 1, 0.78, [
        "I am the youngest here. Vesper's notes are the best place to start.",
        "Matching a recurrence beats guessing its closed form."]),
]

TASKS = [
    ("climate", 2, "A slab ocean 50 m deep absorbs 1 W/m^2 for one year. By how many kelvin does it warm? (seawater 4.0e6 J/m^3/K)", 0.158),
    ("orbital", 3, "Delta-v in km/s for a Hohmann transfer from a 400 km to a 35,786 km circular Earth orbit.", 3.854),
    ("quantum", 2, "Probability of measuring |1> after a Hadamard then an Rx(pi/3) on |0>, to 3 decimals.", 0.5),
    ("cyber", 3, "An LCG runs x_{n+1} = (1103515245*x_n + 12345) mod 2^31 from x_0 = 42. What is x_3?", 1000676753),
    ("world", 1, "A town of 6 residents walks 1.4 m/s; the highway loop is 2.2 km. Minutes to walk it once?", 26.19),
]

LAWS = ["A claim without recomputation is not a result.",
        "Research runs only after the Creator approves it.",
        "Leave the record cleaner than you found it."]


def ensure() -> None:
    if settings.DB_PATH.is_file():
        return
    settings.DATA.mkdir(parents=True, exist_ok=True)
    tmp = settings.DB_PATH.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    now = time.time()
    conn.executemany("INSERT INTO meta VALUES (?,?)",
                     [("tick", str(TICK)), ("last_tick_at", str(now)), ("standalone", "1")])
    ids = {}
    for name, tier, domain, credits, fitness, attempted, verified, curiosity, memories in FOUNDERS:
        cur = conn.execute(
            "INSERT INTO agents (name, tier, domain, credits, fitness, tasks_attempted, "
            "tasks_verified, curiosity, session_id, born_tick, last_tick, traits) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, tier, domain, credits, fitness, attempted, verified, curiosity,
             "pantheon-" + name.lower(), 0, TICK, json.dumps({"founder": True, "domain": domain})))
        ids[name] = cur.lastrowid
        for i, text in enumerate(memories):
            conn.execute("INSERT INTO memory (agent_id, tick, kind, text) VALUES (?,?,?,?)",
                         (cur.lastrowid, TICK - 6 + i * 3, "lesson" if i else "observation", text))
        conn.execute("INSERT INTO ledger (tick, agent_id, delta, reason, balance) VALUES (?,?,?,?,?)",
                     (0, cur.lastrowid, credits, "founding grant", credits))
        conn.execute("INSERT INTO events (tick, kind, agent_id, text) VALUES (?,?,?,?)",
                     (0, "born", cur.lastrowid, "%s woke up in the %s." % (name, domain)))
    for domain, difficulty, question, answer in TASKS:
        conn.execute("INSERT INTO tasks (domain, difficulty, question, spec, check_spec, created_tick, "
                     "reward) VALUES (?,?,?,?,?,?,?)",
                     (domain, difficulty, question, json.dumps({"question": question}),
                      json.dumps({"answer": answer}), 1, 4.0 * difficulty))
    conn.execute("UPDATE tasks SET status='claimed', claimed_by=?, claimed_tick=? WHERE domain='quantum'",
                 (ids["Vesper"], TICK - 1))
    for i, text in enumerate(LAWS):
        conn.execute("INSERT INTO laws (enacted_tick, proposed_tick, text, status) VALUES (?,?,?,?)",
                     (2 + i, 1 + i, text, "active"))
    conn.commit()
    conn.close()
    tmp.replace(settings.DB_PATH)
