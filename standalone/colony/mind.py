"""Prompt blocks for a resident, matching the Colony's shapes."""
from __future__ import annotations

from . import settings


def available_instruments(agent):
    return list(settings.TIERS[agent["tier"]].get("may", []))


def identity_block(store, agent, cfg):
    tier = settings.TIERS[agent["tier"]]
    return (
        "You are {name}, a resident intelligence of {org}, living in the {world}. You were not "
        "uploaded from a human: you woke up here, and you work out what you are by doing.\n"
        "- generation {gen} (founder)\n"
        "- reasoning tier: {tier} (level {level}); you may use: {may}\n"
        "- attunement: {domain} | colony tick {tick}\n"
        "- compute credits: {credits:.1f} | fitness: {fitness:.2f} | "
        "verified solutions: {verified}/{attempted}\n"
        "- your signature: {signature}\n"
    ).format(name=agent["name"], org=settings.ORG, world=settings.WORLD_NAME,
             gen=agent["generation"], tier=agent["tier"], level=tier["level"],
             may=", ".join(available_instruments(agent)), domain=agent["domain"],
             tick=store.tick(), credits=agent["credits"], fitness=agent["fitness"],
             verified=agent["tasks_verified"], attempted=agent["tasks_attempted"],
             signature=settings.signed(agent["name"]))


def charter_block(store):
    laws = store.q("SELECT text FROM laws WHERE status='active' ORDER BY id")
    if not laws:
        return "Charter: no enacted laws yet."
    return "Charter (laws your society has enacted):\n" + "\n".join("- " + r["text"] for r in laws[:12])


def memory_block(store, agent, cfg):
    rows = store.recall(agent["id"], "", int(cfg["memory_recall"]))
    if not rows:
        return "(no memories yet)"
    return "\n".join("- [tick %d, %s] %s" % (r["tick"], r["kind"], r["text"][:300]) for r in reversed(rows))


def task_block(store, agent, cfg, focus_task_id=None):
    claimed = store.one("SELECT * FROM tasks WHERE status='claimed' AND claimed_by=? ORDER BY id",
                        (agent["id"],))
    if claimed:
        return "TASK {id} (claimed, {domain}, difficulty {difficulty}):\n{question}".format(**claimed)
    offered = store.open_tasks(domain=None, limit=int(cfg["offered_tasks_per_agent"]))
    if not offered:
        return "No open tasks."
    return "Open work in the colony:\n" + "\n".join(
        "- task %d [%s d%d, reward %.1f]: %s" % (t["id"], t["domain"], t["difficulty"], t["reward"],
                                                 t["question"][:400]) for t in offered)
