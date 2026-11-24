"""The colony: the world view and the task pool."""
from __future__ import annotations

import re

from bridge import Record, world_view


def _colony(match, query, body):
    return 200, world_view()


def _tasks(match, query, body):
    record = Record()
    names = {a["id"]: a["name"] for a in record.q("SELECT id, name FROM agents")}
    tasks = record.q("SELECT * FROM tasks ORDER BY id DESC")
    for task in tasks:
        task["claimed_by_name"] = names.get(task["claimed_by"]) if task["claimed_by"] else None
        task["authored_by_name"] = names.get(task.get("authored_by")) if task.get("authored_by") else None
    open_count = len([t for t in tasks if t["status"] == "open"])
    return 200, {"tasks": tasks, "open": open_count, "total": len(tasks)}


def _domain(match, query, body):
    domain = match.group("domain")
    record = Record()
    names = {a["id"]: a["name"] for a in record.q("SELECT id, name FROM agents")}
    tasks = record.q("SELECT * FROM tasks WHERE lower(domain)=lower(?) "
                     "ORDER BY CASE status WHEN 'claimed' THEN 0 WHEN 'open' THEN 1 "
                     "ELSE 2 END, id DESC LIMIT 40", (domain,))
    for task in tasks:
        task["claimed_by_name"] = names.get(task["claimed_by"]) if task["claimed_by"] else None
    return 200, {"domain": domain, "tasks": tasks,
                 "open": len([t for t in tasks if t["status"] == "open"])}


ROUTES = [
    ("GET", re.compile(r"^/api/colony$"), _colony),
    ("GET", re.compile(r"^/api/colony/tasks$"), _tasks),
    ("GET", re.compile(r"^/api/colony/domain/(?P<domain>[\w.-]+)$"), _domain),
]
