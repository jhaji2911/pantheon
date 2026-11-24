#!/usr/bin/env python3
"""MIST's own console: one page that holds this whole world in view.

Aggregates what is *actually* true about this host right now — the intelligences
running on it, their chain of command, my memory and skills, the sessions and
subagents, scheduled work, and the company I operate — into a single JSON the
page polls. Every section fails independently and says so; a broken source
reports an error instead of blanking the view.

    python3 serve.py [--port 8790] [--host 127.0.0.1]

Stdlib only. Nothing here writes to any state it reads.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HOME = pathlib.Path.home()
HERMES = HOME / ".hermes"
HERE = pathlib.Path(__file__).resolve().parent
STARTED = time.time()

if str(HERE) not in sys.path:                                    # bridge, store, modules
    sys.path.insert(0, str(HERE))

MODULE_ROUTES: list = []
MODULE_ERROR = ""
try:
    from modules import ROUTES as MODULE_ROUTES, voice as voice_module  # noqa: E402
except Exception as _exc:                                        # noqa: BLE001
    MODULE_ERROR = f"{type(_exc).__name__}: {_exc}"
    MODULE_ROUTES = []


# The inferN desktop/mobile app (Tauri) shows the residents and their controls. Only its
# own origins may call this API cross-origin; everything else stays same-origin. Extend
# with MIST_ALLOWED_ORIGINS (comma-separated) for another trusted shell.
ALLOWED_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
                   "http://localhost:5173", "http://127.0.0.1:5173"} | {
    o.strip() for o in os.environ.get("MIST_ALLOWED_ORIGINS", "").split(",") if o.strip()}

MEMORY_LIMIT = 2200
USER_LIMIT = 1375


# --------------------------------------------------------------------- helpers
def _run(argv, timeout=10) -> str:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return out.stdout or ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _yaml_scalar(path: pathlib.Path, key: str, section: str | None = None) -> str:
    """One scalar out of a YAML file, without a YAML dependency."""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    in_section = section is None
    for line in lines:
        if section is not None:
            if re.match(rf"^{re.escape(section)}:\s*$", line):
                in_section = True
                continue
            if in_section and line and not line.startswith((" ", "\t")):
                break
        if in_section and re.match(rf"^\s*{re.escape(key)}:", line):
            return line.split(":", 1)[1].strip().strip("'\"") or ""
    return ""


def _ro_connect(db: pathlib.Path):
    # A WAL-mode database cannot always be opened read-only when its -shm/-wal
    # sidecars are missing (some SQLite builds need write access to recreate -shm).
    # Fall back to `immutable=1`, which reads a frozen snapshot with no WAL/journal
    # handling — safe for a console that only ever reads the record.
    for uri in (f"file:{db}?mode=ro", f"file:{db}?mode=ro&immutable=1"):
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            conn.execute("SELECT 1").fetchall()  # force the real open (connect is lazy)
            return conn
        except sqlite3.OperationalError:
            continue
    raise RuntimeError(f"cannot open database read-only: {db}")


def _sqlite_rows(db: pathlib.Path, sql: str, params=()) -> list:
    conn = _ro_connect(db)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _http_json(url: str, timeout=4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------- sensors
def sense_self() -> dict:
    config = HERMES / "config.yaml"
    state = {}
    try:
        state = json.loads((HERMES / "gateway_state.json").read_text())
    except (OSError, json.JSONDecodeError):
        state = {}
    gateways = {}
    for line in _run(["launchctl", "list"]).splitlines():
        parts = line.split()
        if len(parts) >= 3 and "hermes" in parts[2]:
            gateways[parts[2]] = {"pid": int(parts[0]) if parts[0].isdigit() else None,
                                  "last_exit": parts[1]}
    return {
        "name": "MIST",
        "profile": "default",
        "model": _yaml_scalar(config, "default", "model"),
        "provider": _yaml_scalar(config, "provider", "model"),
        "host": os.uname().nodename,
        "hermes_home": str(HERMES),
        "gateway_service": "ai.hermes.gateway",
        "gateway": gateways.get("ai.hermes.gateway", {}),
        "version": state.get("code_version") or state.get("version") or "",
        "started": state.get("started_at") or "",
        "all_gateways": gateways,
        "uptime_seconds": round(time.time() - STARTED, 1),
    }


def sense_kin(cfg: dict) -> list:
    profiles_dir = HERMES / "profiles"
    gateways = cfg["self"]["all_gateways"]
    rows = [{
        "kind": "prime",
        "profile": "default",
        "name": "MIST",
        "role": "Prime operator — holds this whole machine in view and answers for it",
        "model": cfg["self"]["model"],
        "provider": cfg["self"]["provider"],
        "gateway": gateways.get("ai.hermes.gateway", {}),
        "skills": cfg["skills"]["total"],
    }]
    if profiles_dir.is_dir():
        for profile in sorted(p for p in profiles_dir.iterdir() if p.is_dir()):
            pconfig = profile / "config.yaml"
            name = "—"
            soul = profile / "SOUL.md"
            if soul.is_file():
                match = re.search(r"\*\*(.+?)\*\*", soul.read_text(errors="replace")[:400])
                if match:
                    name = match.group(1)
            skills = len([p for p in (profile / "skills").rglob("SKILL.md")])
            rows.append({
                "kind": "sibling",
                "profile": profile.name,
                "name": name,
                "role": f"Sibling profile — its own bot, secrets and skills ({skills})",
                "model": _yaml_scalar(pconfig, "default", "model"),
                "provider": _yaml_scalar(pconfig, "provider", "model"),
                "gateway": gateways.get(f"ai.hermes.gateway-{profile.name}", {}),
                "skills": skills,
            })
    rows.append({
        "kind": "spawn",
        "profile": "—",
        "name": "subagents",
        "role": f"Spawning pool — up to {cfg['delegation']['max_concurrent_children']} in "
                "parallel, isolated context, briefed by me, reporting back to me",
        "model": cfg["delegation"]["model"] or f"inherits mine ({cfg['self']['model']})",
        "provider": cfg["self"]["provider"],
        "gateway": {},
        "skills": 0,
    })
    return rows


def sense_memory() -> dict:
    out = {}
    for key, name, limit in (("memory", "MEMORY.md", MEMORY_LIMIT),
                             ("user", "USER.md", USER_LIMIT)):
        path = HERMES / "memories" / name
        try:
            text = path.read_text(errors="replace")
        except OSError as exc:
            out[key] = {"path": str(path), "error": str(exc), "text": "", "chars": 0,
                        "limit": limit}
            continue
        out[key] = {"path": str(path), "text": text, "chars": len(text), "limit": limit,
                    "entries": len([b for b in text.split("\n§\n") if b.strip()])}
    return out


def sense_skills(root: pathlib.Path, limit: int = 400) -> dict:
    items = []
    archived: list = []
    for path in sorted(root.rglob("SKILL.md")):
        try:
            head = path.read_text(errors="replace")[:1200]
        except OSError:
            continue
        name = ""
        description = ""
        if head.startswith("---"):
            for line in head.split("---", 2)[1].splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip("'\"")
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip("'\"")
        relative = path.relative_to(root)
        record = {"name": name or path.parent.name,
                  "category": relative.parts[0] if len(relative.parts) > 1 else ".",
                  "description": description[:200], "path": str(path.parent)}
        # A dot-directory is retired: present on disk, not loaded into context.
        if any(part.startswith(".") for part in relative.parts):
            archived.append(record)
        else:
            items.append(record)
    categories: dict[str, int] = {}
    for item in items:
        categories[item["category"]] = categories.get(item["category"], 0) + 1
    return {"total": len(items), "archived": len(archived),
            "categories": dict(sorted(categories.items())), "items": items[:limit]}


def sense_sessions() -> dict:
    db = HERMES / "state.db"
    if not db.is_file():
        return {"error": "no state.db", "recent": [], "totals": {}}
    try:
        totals = _sqlite_rows(db, """
            SELECT COUNT(*) sessions,
                   COALESCE(SUM(message_count),0) messages,
                   COALESCE(SUM(tool_call_count),0) tool_calls,
                   COALESCE(SUM(input_tokens),0) input_tokens,
                   COALESCE(SUM(output_tokens),0) output_tokens
              FROM sessions""")[0]
        recent = _sqlite_rows(db, """
            SELECT id, source, model, started_at, ended_at, message_count,
                   tool_call_count, input_tokens, output_tokens
              FROM sessions ORDER BY started_at DESC LIMIT 12""")
    except sqlite3.Error as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "recent": [], "totals": {}}
    for row in recent:
        started = row.get("started_at") or 0
        row["started_ago"] = f"{max(0, int(time.time() - started) // 60)}m ago" if started else ""
    return {"totals": totals, "recent": recent}


def sense_delegations() -> dict:
    db = HERMES / "state.db"
    rows: list = []
    error = ""
    if db.is_file():
        try:
            cols = {r["name"] for r in _sqlite_rows(db, "PRAGMA table_info(async_delegations)")}
            if cols:
                order = "rowid DESC"
                for candidate in ("created_at", "started_at", "updated_at"):
                    if candidate in cols:
                        order = f"{candidate} DESC"
                        break
                rows = _sqlite_rows(db, f"SELECT * FROM async_delegations ORDER BY {order} LIMIT 12")
        except sqlite3.Error as exc:
            error = f"{type(exc).__name__}: {exc}"
    if not rows:                      # fall back to the on-disk delegation cache
        live = HERMES / "cache" / "delegation" / "live"
        if live.is_dir():
            for path in sorted(live.iterdir())[-12:]:
                tasks = sorted(path.glob("*.log")) if path.is_dir() else []
                rows.append({"id": path.name, "goals": f"{len(tasks)} task log(s)",
                             "status": "unknown", "transcripts": [str(t) for t in tasks]})
    return {"rows": rows, "error": error}


def sense_cron() -> dict:
    path = HERMES / "cron" / "jobs.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"jobs": [], "error": f"{type(exc).__name__}: {exc}"}
    jobs = data.get("jobs", data) if isinstance(data, dict) else data
    out = []
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict):
            continue
        out.append({
            "id": job.get("id"), "name": job.get("name"),
            "schedule": job.get("schedule") or job.get("cron") or job.get("interval")
                        or job.get("every") or "",
            "enabled": job.get("enabled", True),
            "no_agent": bool(job.get("no_agent")),
            "script": job.get("script") or "",
            "target": job.get("deliver") or job.get("target") or job.get("platform") or "",
            "last_run": job.get("last_run") or job.get("last_run_at") or "",
        })
    return {"jobs": out, "count": len(out)}


def sense_world() -> dict:
    out = {"quorum_console": None, "apps": [], "tasks": [], "processes": []}
    health = _http_json("http://127.0.0.1:8787/api/health")
    out["quorum_console"] = {"up": bool(health), "time": (health or {}).get("time", "")}
    if health:
        state = _http_json("http://127.0.0.1:8787/api/state")
        if state:
            runner = (state.get("server") or {}).get("runner") or {}
            engagements = state.get("engagements") or []
            latest = engagements[0] if engagements else {}
            out["quorum_console"].update({
                "company": (state.get("company") or {}).get("name", ""),
                "profile": state.get("profile", ""),
                "mock": (state.get("mode") or {}).get("mock"),
                "roster": len(state.get("roster") or []),
                "running_jobs": runner.get("running", 0),
                "busy": runner.get("busy", False),
                "tasks": len(state.get("tasks") or []),
                "events": len(state.get("events") or []),
                "latest_engagement": {
                    "id": latest.get("id"), "topic": (latest.get("topic") or "")[:90],
                    "verdict": latest.get("verdict"), "status": latest.get("status"),
                } if latest else None,
            })
        tasks = _http_json("http://127.0.0.1:8787/api/tasks")
        out["tasks"] = (tasks or {}).get("tasks") or []
        apps = _http_json("http://127.0.0.1:8787/api/apps")
        out["apps"] = (apps or {}).get("apps") or []
    listing = _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"])
    for line in listing.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 9 and parts[0] in ("Python", "node", "python3", "ruby"):
            out["processes"].append({"command": parts[0], "pid": parts[1],
                                     "name": parts[-2] if len(parts) > 9 else parts[-1]})
    return out


def sense_charter() -> dict:
    path = HERE / "CHARTER.md"
    try:
        return {"path": str(path), "text": path.read_text(errors="replace")}
    except OSError as exc:
        return {"path": str(path), "text": "", "error": str(exc)}


# ----------------------------------------------------------------- the colony
COLONY = HOME / "Code" / "colony"
COLONY_DB = COLONY / "data" / "colony.db"


def sense_colony() -> dict:
    """My world: the CIs, their economy, their laws and their record — read-only."""
    out: dict = {"path": str(COLONY_DB), "up": COLONY_DB.is_file()}
    if not out["up"]:
        return out
    meta = {r["key"]: r["value"] for r in _sqlite_rows(COLONY_DB,
                                                       "SELECT key, value FROM meta")}
    tick = int(float(meta.get("tick") or 0))
    last = meta.get("last_tick_at")
    out["tick"] = tick
    out["last_tick_at"] = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(last)))
                           if last else "")
    try:
        settings = json.loads((COLONY / "data" / "colony.json").read_text())
        out["directive"] = (settings.get("world_note") or settings.get("mist_note")
                            or settings.get("mist_directive") or settings.get("directive")
                            or "")
    except (OSError, json.JSONDecodeError):
        out["directive"] = ""

    out["agents"] = _sqlite_rows(COLONY_DB, """
        SELECT id, name, tier, domain, generation, credits, fitness, tasks_attempted,
               tasks_verified, failures_streak, status, born_tick, last_tick
          FROM agents ORDER BY CASE tier WHEN 'architect' THEN 0 WHEN 'specialist' THEN 1
                                         ELSE 2 END, fitness DESC""")
    tiers: dict = {}
    for agent in out["agents"]:
        tiers[agent["tier"]] = tiers.get(agent["tier"], 0) + 1
    out["tiers"] = tiers
    out["population"] = {s: len([a for a in out["agents"] if a["status"] == s])
                         for s in ("active", "hibernating", "retired")}

    work = _sqlite_rows(COLONY_DB, """
        SELECT COUNT(*) attempts, COALESCE(SUM(verified),0) solved FROM submissions""")[0]
    work["open_tasks"] = _sqlite_rows(
        COLONY_DB, "SELECT COUNT(*) n FROM tasks WHERE status = 'open'")[0]["n"]
    work["accuracy"] = (round(100.0 * work["solved"] / work["attempts"], 1)
                        if work["attempts"] else None)
    out["work"] = work

    out["economy"] = _sqlite_rows(
        COLONY_DB, "SELECT COALESCE(SUM(credits),0) circulation FROM agents")[0]
    out["ledger"] = _sqlite_rows(
        COLONY_DB, "SELECT tick, delta, reason, balance FROM ledger ORDER BY id DESC LIMIT 8")
    out["laws"] = _sqlite_rows(COLONY_DB,
                               "SELECT id, text, status, enacted_tick FROM laws ORDER BY id")
    out["chronicle"] = _sqlite_rows(
        COLONY_DB, "SELECT tick, kind, text FROM events ORDER BY id DESC LIMIT 14")
    out["petitions"] = _sqlite_rows(
        COLONY_DB, "SELECT id, tick, kind, body, status FROM petitions ORDER BY id DESC LIMIT 8")
    out["petitions_pending"] = len([p for p in out["petitions"]
                                    if p["status"] == "pending"])
    usage = _sqlite_rows(COLONY_DB, """
        SELECT COALESCE(SUM(prompt_tokens + completion_tokens),0) t FROM usage
         WHERE tick = ?""", (tick,))[0]
    day = _sqlite_rows(COLONY_DB, """
        SELECT COALESCE(SUM(prompt_tokens + completion_tokens),0) t FROM usage
         WHERE ts >= ?""", (time.time() - 86400,))[0]
    out["tokens"] = {"this_tick": usage["t"], "last_24h": day["t"]}
    return out


def sense_colony_bridged() -> dict:
    """The colony exactly as GET /api/colony promises it; falls back to the thin sensor."""
    try:
        from bridge import world_view
        return world_view()
    except Exception as exc:                                     # noqa: BLE001
        fallback = sense_colony()
        fallback["bridge_error"] = f"{type(exc).__name__}: {exc}"
        return fallback


# -------------------------------------------------------------------- assemble
def world() -> dict:
    errors = []
    config = HERMES / "config.yaml"
    delegation = {"model": _yaml_scalar(config, "model", "delegation"),
                  "provider": _yaml_scalar(config, "provider", "delegation"),
                  "max_concurrent_children": 10}
    raw = _yaml_scalar(config, "max_concurrent_children", "delegation")
    if raw.isdigit():
        delegation["max_concurrent_children"] = int(raw)

    cfg: dict = {"delegation": delegation}
    payload: dict = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "generated_epoch": time.time(), "errors": errors}
    for key, fn in (("self", sense_self), ("memory", sense_memory),
                    ("skills", lambda: sense_skills(HERMES / "skills")),
                    ("sessions", sense_sessions), ("delegations", sense_delegations),
                    ("cron", sense_cron), ("world", sense_world),
                    ("colony", sense_colony_bridged), ("charter", sense_charter)):
        try:
            payload[key] = fn()
        except Exception as exc:                     # noqa: BLE001 - a view, never a crash
            payload[key] = {"error": f"{type(exc).__name__}: {exc}"}
            errors.append(f"{key}: {type(exc).__name__}: {exc}")
    cfg["self"] = payload["self"]
    cfg["skills"] = payload["skills"]
    try:
        payload["kin"] = sense_kin(cfg)
    except Exception as exc:                          # noqa: BLE001
        payload["kin"] = []
        errors.append(f"kin: {type(exc).__name__}: {exc}")
    return payload


# ---------------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    server_version = "MISTConsole/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # -- module dispatch (the console's capabilities live in modules/) ------
    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace") or "{}")
        except (ValueError, OSError):
            return None

    def _dispatch_module(self, method: str, path: str) -> bool:
        for route_method, pattern, handler in MODULE_ROUTES:
            if route_method != method:
                continue
            match = pattern.match(path)
            if not match:
                continue
            query = parse_qs(urlparse(self.path).query)
            body = self._read_json() if method == "POST" else None
            try:
                status, payload = handler(match, query, body)
            except Exception as exc:                             # noqa: BLE001
                status, payload = 500, {"error": f"{type(exc).__name__}: {exc}"}
            body_bytes = json.dumps(payload, default=str).encode("utf-8")
            self._send(status, body_bytes, "application/json; charset=utf-8")
            return True
        return False

    # -- static assets: the UI's own modules -------------------------------
    def _serve_static(self, relpath: str) -> bool:
        target = (HERE / "static" / unquote(relpath)).resolve()
        static_root = (HERE / "static").resolve()
        if not str(target).startswith(str(static_root)) or not target.is_file():
            return False
        ctype = {
            ".js": "text/javascript; charset=utf-8",
            ".mjs": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".svg": "image/svg+xml",
            ".json": "application/json; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)
        return True

    def _cors_headers(self):
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        # CORS preflight for the inferN app; other origins get no grant.
        self.send_response(204)
        if self.headers.get("Origin") in ALLOWED_ORIGINS:
            self._cors_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in ("/", "/index.html"):
            try:
                body = (HERE / "index.html").read_bytes()
            except OSError as exc:
                return self._send(500, str(exc).encode(), "text/plain; charset=utf-8")
            return self._send(200, body, "text/html; charset=utf-8")
        if path.startswith("/api/static/"):
            if self._serve_static(path[len("/api/static/"):]):
                return None
        if path == "/api/world":
            body = json.dumps(world(), default=str).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")
        if path == "/api/modules":
            return self._send(200, json.dumps({
                "routes": len(MODULE_ROUTES),
                "loaded": sorted({pattern.pattern for _, pattern, _ in MODULE_ROUTES}),
                "error": MODULE_ERROR,
            }).encode("utf-8"), "application/json; charset=utf-8")
        if path == "/api/health":
            return self._send(200, b'{"ok": true}', "application/json")
        if self._dispatch_module("GET", path):
            return None
        return self._send(404, b'{"error": "no route"}', "application/json")

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        voice_match = re.fullmatch(r"/api/voice/([\w.-]+)/turn", path)
        if voice_match:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, b'{"error":"invalid content length"}', "application/json")
            if length <= 0 or length > voice_module.MAX_AUDIO_BYTES:
                return self._send(413, b'{"error":"audio body must be between 1 byte and 6 MB"}',
                                  "application/json")
            if not (self.headers.get("Content-Type") or "").lower().startswith("audio/wav"):
                return self._send(415, b'{"error":"send mono PCM as audio/wav"}', "application/json")
            audio = self.rfile.read(length)
            if len(audio) != length:
                return self._send(400, b'{"error":"incomplete audio body"}', "application/json")
            status, payload = voice_module.turn(unquote(voice_match.group(1)), audio)
            return self._send(status, json.dumps(payload, default=str).encode("utf-8"),
                              "application/json; charset=utf-8")
        if self._dispatch_module("POST", path):
            return None
        return self._send(404, b'{"error": "no route"}', "application/json")


def serve(host: str, port: int):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"MIST console → http://{host}:{port}  (pid {os.getpid()})", flush=True)
    httpd.serve_forever()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)
    threading.Thread(target=lambda: None).start()
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
