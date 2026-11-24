"""The console's own store: conversations with CIs, and the assemblies they speak in.

Deliberately separate from the colony's database. The colony's record belongs to the
colony; what MIST asked its CIs in the console is MIST's own business and lives here.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import time
import uuid

DATA = pathlib.Path(__file__).resolve().parent / "data"
DB = DATA / "console.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS intercom (
    id TEXT PRIMARY KEY,
    ci TEXT NOT NULL,
    ts REAL NOT NULL,
    question TEXT NOT NULL,
    reply TEXT NOT NULL,
    model TEXT,
    ms INTEGER,
    tokens INTEGER
);
CREATE INDEX IF NOT EXISTS idx_intercom_ci ON intercom(ci, ts DESC);

CREATE TABLE IF NOT EXISTS assemblies (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    topic TEXT NOT NULL,
    created REAL NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS world_artifacts (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS world_places (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    x REAL NOT NULL,
    z REAL NOT NULL,
    hue INTEGER NOT NULL,
    reason TEXT NOT NULL,
    participants TEXT NOT NULL,
    interactions INTEGER NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS world_assets (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    owner_profile TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    color TEXT NOT NULL,
    width REAL NOT NULL,
    depth REAL NOT NULL,
    height REAL NOT NULL,
    x REAL NOT NULL,
    z REAL NOT NULL,
    model TEXT NOT NULL,
    billing_source TEXT NOT NULL,
    cost REAL NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    brief TEXT NOT NULL,
    source_tick INTEGER NOT NULL DEFAULT 0,
    source_event_ids TEXT NOT NULL DEFAULT '[]',
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_assets_created ON world_assets(created DESC);
CREATE TABLE IF NOT EXISTS mind_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    name TEXT NOT NULL,
    model TEXT,
    ok INTEGER NOT NULL,
    error TEXT,
    tokens INTEGER NOT NULL DEFAULT 0,
    ms INTEGER,
    observation TEXT NOT NULL,
    thought TEXT,
    goal TEXT,
    action TEXT,
    outcome TEXT
);
CREATE INDEX IF NOT EXISTS idx_mind_log_name ON mind_log(name, ts DESC);
CREATE INDEX IF NOT EXISTS idx_mind_log_ts ON mind_log(ts);
CREATE TABLE IF NOT EXISTS mind_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    salience REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mind_memory_name ON mind_memory(name, ts DESC);
CREATE TABLE IF NOT EXISTS life_state (
    name TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS life_plans (
    name TEXT NOT NULL,
    day INTEGER NOT NULL,
    plan TEXT NOT NULL,
    created REAL NOT NULL,
    model TEXT,
    PRIMARY KEY (name, day)
);
CREATE TABLE IF NOT EXISTS relations (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    affinity REAL NOT NULL DEFAULT 0,
    familiarity INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    updated REAL NOT NULL,
    PRIMARY KEY (a, b)
);
CREATE TABLE IF NOT EXISTS research_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    topic TEXT NOT NULL,
    why TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decided REAL,
    job_id TEXT,
    engagement_id INTEGER,
    verdict TEXT,
    paper_path TEXT,
    summary TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS frontier_papers (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '',
    published TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    domains TEXT NOT NULL DEFAULT '[]',
    score REAL NOT NULL DEFAULT 0,
    signals TEXT NOT NULL DEFAULT '[]',
    fetched REAL NOT NULL,
    used_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_frontier_score ON frontier_papers(score DESC);
CREATE TABLE IF NOT EXISTS research_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    author TEXT NOT NULL,
    proposal_id INTEGER,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    cites TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS god_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    target TEXT,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mind_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    name TEXT NOT NULL,
    brief TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    asset_id TEXT
);
"""


def _conn() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mind_log)")}
    if "locality" not in cols:   # added with local inference; older rows were all cloud
        conn.execute("ALTER TABLE mind_log ADD COLUMN locality TEXT NOT NULL DEFAULT 'cloud'")
        conn.execute("ALTER TABLE mind_log ADD COLUMN kind TEXT NOT NULL DEFAULT 'moment'")
    rcols = {r[1] for r in conn.execute("PRAGMA table_info(research_proposals)")}
    for col in ("paper", "hypothesis", "test", "builds_on", "digest_sent"):   # novelty brief, added later
        if col not in rcols:
            conn.execute("ALTER TABLE research_proposals ADD COLUMN %s %s" %
                         (col, "REAL" if col == "digest_sent" else "TEXT"))
    return conn


def save_exchange(result: dict) -> dict:
    """Store one question/answer pair with a CI."""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ci": result["ci"],
        "ts": result.get("ts") or time.time(),
        "question": result["question"],
        "reply": result["reply"],
        "model": result.get("model"),
        "ms": result.get("ms"),
        "tokens": result.get("tokens"),
    }
    with _conn() as conn:
        conn.execute("INSERT INTO intercom(id, ci, ts, question, reply, model, ms, tokens) "
                     "VALUES(:id, :ci, :ts, :question, :reply, :model, :ms, :tokens)", entry)
    return entry


def thread(ci: str, limit: int = 40) -> list:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM intercom WHERE lower(ci)=lower(?) "
                            "ORDER BY ts DESC LIMIT ?", (ci, limit)).fetchall()
    return [dict(r) for r in rows]


def save_assembly(result: dict) -> dict:
    assembly_id = uuid.uuid4().hex[:12]
    result = dict(result, id=assembly_id)
    with _conn() as conn:
        conn.execute("INSERT INTO assemblies(id, kind, topic, created, payload) "
                     "VALUES(?,?,?,?,?)",
                     (assembly_id, result["kind"], result["topic"],
                      result["created"], json.dumps(result)))
    return result


def assemblies(limit: int = 25) -> list:
    with _conn() as conn:
        rows = conn.execute("SELECT payload FROM assemblies ORDER BY created DESC LIMIT ?",
                            (limit,)).fetchall()
    out = []
    for row in rows:
        payload = json.loads(row["payload"])
        out.append({"id": payload["id"], "kind": payload["kind"], "topic": payload["topic"],
                    "created": payload["created"], "cis": payload.get("cis", []),
                    "rounds": payload.get("rounds"), "status": payload.get("status"),
                    "speakers": len(payload.get("transcript") or []),
                    "transcript_len": sum(len(line.get("text") or "")
                                          for line in payload.get("transcript") or []),
                    "spend": payload.get("spend")})
    return out


def interactions_for_ci(ci: str, limit: int = 20) -> list:
    """Assemblies are the durable social edges between CIs; filter their saved transcripts."""
    key = (ci or "").lower()
    with _conn() as conn:
        rows = conn.execute("SELECT payload FROM assemblies ORDER BY created DESC LIMIT 200").fetchall()
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            continue
        names = payload.get("cis") or []
        if key not in {str(name).lower() for name in names}:
            continue
        others = [name for name in names if str(name).lower() != key]
        out.append({
            "id": payload.get("id"), "kind": payload.get("kind"),
            "topic": payload.get("topic"), "created": payload.get("created"),
            "peers": others, "rounds": payload.get("rounds"),
            "participants": payload.get("participants") or [],
            "transcript": payload.get("transcript") or [],
        })
        if len(out) >= limit:
            break
    return out


def assembly(assembly_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT payload FROM assemblies WHERE id=?",
                           (assembly_id,)).fetchone()
    if not row:
        return None
    return json.loads(row["payload"])


def stats() -> dict:
    with _conn() as conn:
        return {
            "exchanges": conn.execute("SELECT COUNT(*) FROM intercom").fetchone()[0],
            "assemblies": conn.execute("SELECT COUNT(*) FROM assemblies").fetchone()[0],
            "tokens_spent": conn.execute(
                "SELECT COALESCE(SUM(tokens),0) FROM intercom").fetchone()[0],
        }


def upsert_world_artifact(artifact: dict) -> dict:
    """Persist one evidence-backed world artifact in the console's own database."""
    now=time.time()
    content=json.dumps(artifact.get("content") or {},sort_keys=True)
    with _conn() as conn:
        row=conn.execute("SELECT created,content,updated FROM world_artifacts WHERE id=?",
                         (artifact["id"],)).fetchone()
        if row and row["content"]==content:
            created,updated=row["created"],row["updated"]
        else:
            created=row["created"] if row else now
            updated=now
            conn.execute("INSERT INTO world_artifacts(id,owner,kind,title,content,source_ref,created,updated) "
                         "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                         "owner=excluded.owner,kind=excluded.kind,title=excluded.title,content=excluded.content,"
                         "source_ref=excluded.source_ref,updated=excluded.updated",
                         (artifact["id"],artifact.get("owner") or "",artifact.get("kind") or "note",
                          artifact.get("title") or "artifact",content,artifact.get("source_ref") or "",
                          created,updated))
    return {**artifact,"content":json.loads(content),"created":created,"updated":updated}


def world_artifacts(limit: int = 100) -> list:
    with _conn() as conn:
        rows=conn.execute("SELECT * FROM world_artifacts ORDER BY updated DESC LIMIT ?",(limit,)).fetchall()
    return [{**dict(r),"content":json.loads(r["content"])} for r in rows]


def upsert_world_place(place: dict) -> dict:
    now=time.time();participants=json.dumps(place.get("participants") or [])
    with _conn() as conn:
        row=conn.execute("SELECT created FROM world_places WHERE id=?",(place["id"],)).fetchone()
        created=row["created"] if row else now
        conn.execute("INSERT INTO world_places(id,name,kind,x,z,hue,reason,participants,interactions,created) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                     "name=excluded.name,kind=excluded.kind,x=excluded.x,z=excluded.z,hue=excluded.hue,"
                     "reason=excluded.reason,participants=excluded.participants,interactions=excluded.interactions",
                     (place["id"],place["name"],place.get("kind") or "social",float(place["x"]),float(place["z"]),
                      int(place.get("hue") or 210),place.get("reason") or "",participants,
                      int(place.get("interactions") or 0),created))
    return {**place,"participants":json.loads(participants),"created":created}


def world_places() -> list:
    with _conn() as conn:
        rows=conn.execute("SELECT * FROM world_places ORDER BY interactions DESC,created DESC").fetchall()
    return [{**dict(r),"participants":json.loads(r["participants"]),"dynamic":True} for r in rows]


def create_world_asset(asset: dict) -> dict:
    """Append an immutable, attributed asset generated for the Pantheon."""
    columns = ("id", "owner", "owner_profile", "kind", "name", "description", "color",
               "width", "depth", "height", "x", "z", "model", "billing_source", "cost",
               "tokens", "brief", "source_tick", "source_event_ids", "created")
    values = [asset.get(k) for k in columns]
    values[18] = json.dumps(asset.get("source_event_ids") or [])
    with _conn() as conn:
        conn.execute("INSERT INTO world_assets(" + ",".join(columns) + ") VALUES(" +
                     ",".join("?" for _ in columns) + ")", values)
        row = conn.execute("SELECT * FROM world_assets WHERE id=?", (asset["id"],)).fetchone()
    result = dict(row)
    result["source_event_ids"] = json.loads(result["source_event_ids"])
    result["dynamic"] = True
    return result


def world_assets(limit: int = 100) -> list:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM world_assets ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["source_event_ids"] = json.loads(item["source_event_ids"])
        item["dynamic"] = True
        out.append(item)
    return out


def collaboration_pairs(min_meetings: int = 2) -> list:
    """Repeated assembly pairings are evidence that a shared place is useful."""
    with _conn() as conn:
        rows=conn.execute("SELECT payload FROM assemblies ORDER BY created DESC LIMIT 1000").fetchall()
    pairs={}
    for row in rows:
        try: payload=json.loads(row["payload"])
        except (TypeError,ValueError): continue
        names=sorted({str(n) for n in (payload.get("cis") or [])},key=str.lower)
        for i,left in enumerate(names):
            for right in names[i+1:]:
                key=(left.lower(),right.lower())
                item=pairs.setdefault(key,{"participants":[left,right],"interactions":0,"created":0,"topic":""})
                item["interactions"]+=1
                created=float(payload.get("created") or 0)
                if created>=item["created"]:
                    item["created"]=created;item["topic"]=str(payload.get("topic") or "")
    return sorted((v for v in pairs.values() if v["interactions"]>=min_meetings),
                  key=lambda x:(-x["interactions"],-x["created"]))


# ------------------------------------------------------------------ minds
def log_mind(entry: dict) -> int:
    """Append one decision: what the CI saw, what it thought, did, and what happened."""
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO mind_log(ts,name,model,ok,error,tokens,ms,observation,thought,goal,action,outcome,"
            "locality,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (entry["ts"], entry["name"], entry.get("model"), 1 if entry.get("ok") else 0,
             entry.get("error"), int(entry.get("tokens") or 0), entry.get("ms"),
             json.dumps(entry.get("observation") or {}, ensure_ascii=False),
             entry.get("thought"), entry.get("goal"),
             json.dumps(entry.get("action")) if entry.get("action") is not None else None,
             entry.get("outcome"), entry.get("locality") or "cloud", entry.get("kind") or "moment"))
        return cur.lastrowid


def mind_log(name: str | None = None, limit: int = 30) -> list:
    sql, params = "SELECT * FROM mind_log", []
    if name:
        sql += " WHERE lower(name)=lower(?)"
        params.append(name)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["ok"] = bool(item["ok"])
        item["observation"] = json.loads(item["observation"] or "{}")
        item["action"] = json.loads(item["action"]) if item["action"] else None
        out.append(item)
    return out


def mind_tokens_since(ts: float, locality: str = "cloud") -> int:
    """Tokens spent since `ts` on one route; the daily cap applies to cloud tokens only."""
    with _conn() as conn:
        return int(conn.execute("SELECT COALESCE(SUM(tokens),0) FROM mind_log WHERE ts>=? AND locality=?",
                                (ts, locality)).fetchone()[0])


def mind_usage(since: float) -> list:
    """Calls, failures, tokens and latency since `since`, by route, model and kind of thinking."""
    with _conn() as conn:
        rows = conn.execute("SELECT locality, COALESCE(model,'—') AS model, kind, COUNT(*) AS calls, "
                            "SUM(CASE WHEN ok THEN 0 ELSE 1 END) AS failed, COALESCE(SUM(tokens),0) AS tokens, "
                            "CAST(AVG(ms) AS INTEGER) AS avg_ms FROM mind_log WHERE ts>=? "
                            "GROUP BY locality, model, kind ORDER BY calls DESC", (since,)).fetchall()
    return [dict(r) for r in rows]


def remember(name: str, kind: str, text: str, salience: float, ts: float | None = None) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO mind_memory(ts,name,kind,text,salience) VALUES(?,?,?,?,?)",
                     (ts or time.time(), name, kind, text[:400], max(0.0, min(1.0, salience))))


def recall_episodes(name: str, limit: int = 8, now: float | None = None) -> list:
    """Most useful episodes: salience weighted by recency (half-life one hour)."""
    now = now or time.time()
    with _conn() as conn:
        rows = conn.execute("SELECT ts,kind,text,salience FROM mind_memory WHERE lower(name)=lower(?) "
                            "ORDER BY id DESC LIMIT 60", (name,)).fetchall()
    scored = sorted((dict(r) for r in rows),
                    key=lambda r: -(r["salience"] + 0.5 ** ((now - r["ts"]) / 3600.0)))
    return sorted(scored[:limit], key=lambda r: r["ts"])


def request_asset(name: str, brief: str, ts: float | None = None) -> bool:
    """Queue one asset brief from a CI; each CI may hold at most one pending request."""
    with _conn() as conn:
        if conn.execute("SELECT 1 FROM mind_requests WHERE lower(name)=lower(?) AND status='pending'",
                        (name,)).fetchone():
            return False
        conn.execute("INSERT INTO mind_requests(ts,name,brief) VALUES(?,?,?)",
                     (ts or time.time(), name, brief))
        return True


def next_asset_request() -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM mind_requests WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


def finish_asset_request(request_id: int, status: str, asset_id: str | None = None) -> None:
    with _conn() as conn:
        conn.execute("UPDATE mind_requests SET status=?, asset_id=? WHERE id=?",
                     (status, asset_id, request_id))


# ------------------------------------------------------------------ lives
def save_life(name: str, state: dict) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO life_state(name,state,updated) VALUES(?,?,?) "
                     "ON CONFLICT(name) DO UPDATE SET state=excluded.state, updated=excluded.updated",
                     (name.lower(), json.dumps(state), time.time()))


def load_life(name: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT state FROM life_state WHERE name=?", (name.lower(),)).fetchone()
    return json.loads(row["state"]) if row else None


def save_plan(name: str, day: int, plan: dict, model: str | None) -> None:
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO life_plans(name,day,plan,created,model) VALUES(?,?,?,?,?)",
                     (name.lower(), day, json.dumps(plan), time.time(), model))


def plan_for(name: str, day: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT plan FROM life_plans WHERE name=? AND day=?", (name.lower(), day)).fetchone()
    return json.loads(row["plan"]) if row else None


def touch_relation(a: str, b: str, familiarity: int = 1, affinity_delta: float = 0.0,
                   note: str | None = None) -> None:
    """Directed: how `a` regards `b`."""
    with _conn() as conn:
        conn.execute("INSERT INTO relations(a,b,affinity,familiarity,note,updated) VALUES(?,?,0,0,'',?) "
                     "ON CONFLICT(a,b) DO NOTHING", (a.lower(), b.lower(), time.time()))
        conn.execute("UPDATE relations SET familiarity=familiarity+?, "
                     "affinity=MAX(-1.0, MIN(1.0, affinity+?)), note=COALESCE(?, note), updated=? "
                     "WHERE a=? AND b=?",
                     (familiarity, affinity_delta, note[:200] if note else None, time.time(), a.lower(), b.lower()))


def relations_of(name: str, limit: int = 8) -> list:
    with _conn() as conn:
        rows = conn.execute("SELECT b AS name, affinity, familiarity, note FROM relations WHERE a=? "
                            "ORDER BY familiarity DESC, updated DESC LIMIT ?", (name.lower(), limit)).fetchall()
    return [dict(r) for r in rows]


def episodes_since(name: str, ts: float) -> list:
    with _conn() as conn:
        rows = conn.execute("SELECT ts,kind,text,salience FROM mind_memory WHERE lower(name)=lower(?) AND ts>? "
                            "AND kind!='reflection' ORDER BY id", (name, ts)).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ the creator's words
def log_god_word(kind: str, target: str | None, text: str, ts: float | None = None) -> dict:
    with _conn() as conn:
        cur = conn.execute("INSERT INTO god_words(ts,kind,target,text) VALUES(?,?,?,?)",
                           (ts or time.time(), kind, target, text))
        return dict(conn.execute("SELECT * FROM god_words WHERE id=?", (cur.lastrowid,)).fetchone())


def god_words(limit: int = 30) -> list:
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM god_words ORDER BY id DESC LIMIT ?", (limit,))]


# ------------------------------------------------------------------ research proposals
def propose_research(name: str, kind: str, topic: str, why: str, ts: float | None = None,
                     brief: dict | None = None) -> int | None:
    """One open (pending or running) proposal per resident; returns its id or None."""
    with _conn() as conn:
        if conn.execute("SELECT 1 FROM research_proposals WHERE lower(name)=lower(?) "
                        "AND status IN ('pending','approved','running')", (name,)).fetchone():
            return None
        b = brief or {}
        cur = conn.execute("INSERT INTO research_proposals(ts,name,kind,topic,why,paper,hypothesis,test,builds_on) "
                           "VALUES(?,?,?,?,?,?,?,?,?)",
                           (ts or time.time(), name, kind, topic, why, b.get("paper"), b.get("hypothesis"),
                            b.get("test"), b.get("builds_on")))
        return cur.lastrowid


def research_proposals(status: str | None = None, limit: int = 50, name: str | None = None) -> list:
    sql, params, where = "SELECT * FROM research_proposals", [], []
    if status:
        where.append("status=?"); params.append(status)
    if name:
        where.append("lower(name)=lower(?)"); params.append(name)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def research_proposal(pid: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM research_proposals WHERE id=?", (pid,)).fetchone()
    return dict(row) if row else None


def update_research(pid: int, **fields) -> None:
    allowed = {"status", "decided", "job_id", "engagement_id", "verdict", "paper_path", "summary", "error",
               "digest_sent"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    with _conn() as conn:
        conn.execute("UPDATE research_proposals SET " + ",".join(k + "=?" for k in keys) + " WHERE id=?",
                     [fields[k] for k in keys] + [pid])


# ------------------------------------------------------------------ frontier papers, notes, kv
def save_frontier(papers: list) -> int:
    """Insert new papers; known ids keep their `used_by` but take the fresh score. Returns new rows."""
    fresh = 0
    with _conn() as conn:
        for p in papers:
            had = conn.execute("SELECT 1 FROM frontier_papers WHERE id=?", (p["id"],)).fetchone()
            conn.execute(
                "INSERT INTO frontier_papers(id,source,title,abstract,authors,published,url,domains,score,signals,fetched) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET score=excluded.score, "
                "signals=excluded.signals, domains=excluded.domains",
                (p["id"], p["source"], p["title"], p["abstract"], p["authors"], p["published"], p["url"],
                 json.dumps(p["domains"]), p["score"], json.dumps(p["signals"]), time.time()))
            fresh += 0 if had else 1
    return fresh


def _paper(row) -> dict:
    d = dict(row)
    d["domains"], d["signals"] = json.loads(d["domains"]), json.loads(d["signals"])
    return d


def frontier_for(domain: str | None, limit: int = 3, unused: bool = True) -> list:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM frontier_papers " + ("WHERE used_by IS NULL " if unused else "") +
                            "ORDER BY score DESC LIMIT 400").fetchall()
    out = [_paper(r) for r in rows]
    if domain:
        out = [p for p in out if domain in p["domains"]] or out
    return out[:limit]


def frontier_paper(pid: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM frontier_papers WHERE lower(id)=lower(?)", (pid,)).fetchone()
    return _paper(row) if row else None


def mark_paper_used(pid: str, name: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE frontier_papers SET used_by=? WHERE lower(id)=lower(?) AND used_by IS NULL", (name, pid))


def frontier_count() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM frontier_papers").fetchone()[0]


def add_note(author: str, kind: str, text: str, proposal_id: int | None = None, cites=None, ts=None) -> int:
    with _conn() as conn:
        return conn.execute("INSERT INTO research_notes(ts,author,proposal_id,kind,text,cites) VALUES(?,?,?,?,?,?)",
                            (ts or time.time(), author, proposal_id, kind, text, json.dumps(cites or []))).lastrowid


def notes(limit: int = 6, exclude_author: str | None = None) -> list:
    sql, params = "SELECT * FROM research_notes", []
    if exclude_author:
        sql += " WHERE lower(author)!=lower(?)"; params.append(exclude_author)
    with _conn() as conn:
        return [dict(r) for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?", params + [limit])]


def kv_get(key: str, default: str | None = None) -> str | None:
    with _conn() as conn:
        row = conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row[0] if row else default


def kv_set(key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))
