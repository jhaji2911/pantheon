"""Did the verifier's own bug fail CIs who were right? And is the fix sound?

Rescores the real failed submissions against the corrected expectation, and checks the
generator can no longer emit an unwinnable task.
"""
import json
import pathlib
import random
import sqlite3
import sys

REPO = pathlib.Path.home() / "Code" / "colony"
sys.path.insert(0, str(REPO))
from colony import domains                                         # noqa: E402

DB = REPO / "data" / "colony.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row


def slope_per_month(series):
    n = len(series)
    mx = (n - 1) / 2.0
    my = sum(series) / n
    den = sum((i - mx) ** 2 for i in range(n)) or 1.0
    return sum((i - mx) * (y - my) for i, y in enumerate(series)) / den


print("=== 1. the climatology disagreement, in numbers ===")
for task_id in (5, 13, 6):
    row = conn.execute("SELECT id, question, check_spec FROM tasks WHERE id=?",
                       (task_id,)).fetchone()
    if not row:
        continue
    series = [float(x) for x in json.loads(row["check_spec"])["series"]]
    slope = slope_per_month(series)
    per_year, per_decade = slope * 12, slope * 120
    question_unit = "per DECADE" if "DECADE" in row["question"] else "per YEAR"
    print(f"  task {task_id}: question asks {question_unit}")
    print(f"    truth per year   = {per_year:.6f}   (what the verifier used to demand)")
    print(f"    truth per decade = {per_decade:.6f}   (what the question asks for)")

print("\n=== 2. rescorinG the real failed submissions ===")
rows = conn.execute("""
    SELECT s.id, s.task_id, a.name, s.answer, s.detail
      FROM submissions s JOIN agents a ON a.id = s.agent_id
     WHERE s.verified = 0 AND s.task_id IN (5, 13)
     ORDER BY s.id""").fetchall()
for row in rows:
    spec = conn.execute("SELECT check_spec FROM tasks WHERE id=?", (row["task_id"],)).fetchone()
    series = [float(x) for x in json.loads(spec["check_spec"])["series"]]
    per_decade = slope_per_month(series) * 120
    try:
        answer = float(str(row["answer"]).strip())
    except ValueError:
        print(f"  {row['name']:10} task {row['task_id']} answer={str(row['answer'])[:20]!r} "
              f"-> not numeric")
        continue
    rel = abs(answer - per_decade) / abs(per_decade)
    verdict = "WOULD NOW PASS" if rel <= 1e-3 else f"still off by {rel:.1%}"
    print(f"  {row['name']:10} task {row['task_id']:>3} answered {answer:<10} "
          f"truth(decade) {per_decade:<10.4f} -> {verdict}")

print("\n=== 3. can the generator still emit an unwinnable task? ===")
rng = random.Random(7)
kinds = {}
for _ in range(400):
    task = domains.make_task("cyber", 2, rng)
    kind = task["spec"]["kind"]
    kinds[kind] = kinds.get(kind, 0) + 1
print(f"  400 cyber tasks generated: {kinds}")
assert "pow" not in kinds, "an unwinnable task kind is still being generated"
print("  no proof-of-work tasks: OK")

print("\n=== 4. question and verifier now agree ===")
rng = random.Random(11)
checked = 0
for _ in range(60):
    task = domains.make_task("climate", 1, rng)
    if task["spec"]["kind"] != "trend":
        continue
    series = [float(x) for x in task["spec"]["series"]]
    slope = slope_per_month(series)
    asked_decade = "DECADE" in task["question"]
    ok, score, detail = domains.verify(task["check_spec"], slope * (120 if asked_decade else 12))
    assert ok, f"a CI answering in the asked unit was failed: {detail}"
    checked += 1
print(f"  {checked} generated trend tasks: a CI answering in the unit the question names "
      f"now verifies correct in every case: OK")

print("\n=== 5. the verifier still rejects wrong answers ===")
rng = random.Random(3)
task = domains.make_task("climate", 1, rng)
while task["spec"]["kind"] != "trend":
    task = domains.make_task("climate", 1, rng)
series = [float(x) for x in task["spec"]["series"]]
for wrong in (slope_per_month(series) * 12, 0.0, 99.0):
    ok, score, detail = domains.verify(task["check_spec"], wrong)
    print(f"  answer {wrong:<12.6f} -> verified={ok}  {detail[:70]}")
    assert not ok, "a wrong answer was verified"
print("  wrong answers are still rejected: OK")
conn.close()
