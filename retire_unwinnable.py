"""Retire the proof-of-work tasks: work the colony's own instruments cannot do.

Written as the overseer, through the colony's own Store, with an event so the chronicle
shows exactly what was touched and why. Idempotent: a second run finds nothing to do.
"""
import json
import pathlib
import sys

REPO = pathlib.Path.home() / "Code" / "colony"
sys.path.insert(0, str(REPO))
from colony import store as store_mod                                # noqa: E402

store = store_mod.Store()
rows = store.q("SELECT id, domain, difficulty, status, claimed_by, question FROM tasks")
targets = []
for row in rows:
    spec = row.get("question") or ""
    full = store.one("SELECT spec, check_spec FROM tasks WHERE id=?", (row["id"],))
    kind = ""
    try:
        kind = json.loads(full["check_spec"]).get("kind", "")
    except (ValueError, TypeError):
        pass
    if kind == "pow":
        targets.append((row, kind))

print(f"tasks in the pool: {len(rows)} · unwinnable (kind=pow): {len(targets)}")
for row, kind in targets:
    print(f"  task {row['id']}: {row['status']}, claimed_by={row['claimed_by']}, "
          f"{row['question'][:70]}…")

retired = 0
for row, _ in targets:
    if row["status"] in ("open", "claimed"):
        store.conn.execute("UPDATE tasks SET status='expired', claimed_by=NULL, "
                           "claimed_tick=NULL WHERE id=?", (row["id"],))
        store.conn.commit()
        store.event("expired", "MIST retired task %d: unwinnable with a CI's instruments "
                               "(compute is arithmetic only — no loops, no hash, so the "
                               "nonce could only be guessed at)." % row["id"])
        retired += 1

print(f"\nretired {retired} task(s)")
still = store.q("SELECT id, status FROM tasks WHERE status IN ('open','claimed') "
                "ORDER BY id")
print(f"pool now holds {len(still)} open/claimed task(s): "
      f"{[(t['id'], t['status']) for t in still]}")
print("\nlast 4 chronicle lines:")
for row in store.q("SELECT tick, kind, text FROM events ORDER BY id DESC LIMIT 4"):
    print(f"  tick {row['tick']} · {row['kind']} · {row['text'][:110]}")
