"""Two structural questions raised by tick 6's failures.

1. Kestrel said: "My compute tool rejected the hash expression as a syntax error."
   Is the proof-of-work task even solvable with the instruments a CI actually has?
2. Three CIs failed the same climate task with wild answers (2.3333, 0.54, placeholder)
   against expected 0.235575. Recompute the truth here and see which side is wrong.
"""
import ast
import hashlib
import json
import pathlib
import sqlite3
import sys

REPO = pathlib.Path.home() / "Code" / "colony"
sys.path.insert(0, str(REPO))
from colony import instruments                                        # noqa: E402

DB = REPO / "data" / "colony.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

print("=== 1. can a CI compute a sha256 proof-of-work with its own instruments? ===")
try:
    result = instruments.run(None, "worker", "compute",
                             {"expression": "int(hashlib.sha256(b'colony-5348161:0').hexdigest()[:4], 16)"})
    print("  hashlib expression ->", str(result)[:200])
except Exception as exc:                                              # noqa: BLE001
    print(f"  hashlib expression -> REFUSED: {type(exc).__name__}: {str(exc)[:200]}")

for expr in ("2*3", "sum([1,2,3])", "min([3,1,2])", "pow(2,10)",
             "hashlib.sha256(b'x').hexdigest()"):
    ok, detail = None, ""
    try:
        out = instruments.safe_eval(expr)
        ok, detail = True, str(out)[:60]
    except Exception as exc:                                          # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {str(exc)[:80]}"
    print(f"  {'OK  ' if ok else 'NO  '} {expr:42} {detail}")

source = pathlib.Path(REPO / "colony" / "instruments.py").read_text()
whitelisted = sorted({node.split(".")[-1] for node in
                      [line.strip().rstrip(",") for line in source.splitlines()
                       if "ast." in line and "Name" not in line][:400]})
print(f"\n  AST whitelist mentions {len(whitelisted)} node types; "
      f"'Attribute' allowed: {'ast.Attribute' in source} · "
      f"'Call' allowed: {'ast.Call' in source} · "
      f"'Import' allowed: {'ast.Import' in source}")

print("\n=== 2. the climate task three CIs failed ===")
rows = conn.execute("SELECT id, domain, difficulty, reward, status, attempts, question, "
                    "spec, check_spec FROM tasks WHERE id IN (13, 5, 6)").fetchall()
for row in rows:
    print(f"\n  task {row['id']} · {row['domain']} d{row['difficulty']} · {row['status']} "
          f"· attempts {row['attempts']} · reward {row['reward']}")
    print(f"    question: {row['question'][:220]}")
    print(f"    check_spec: {row['check_spec'][:300]}")

print("\n  --- recomputing the truth for the task the CIs failed ---")
for row in rows:
    spec = json.loads(row["spec"] or "{}")
    check = json.loads(row["check_spec"] or "{}")
    series = check.get("series") or spec.get("series")
    if row["domain"] == "climate" and series:
        n = len(series)
        mean_x = (n - 1) / 2.0
        mean_y = sum(series) / n
        num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(series))
        den = sum((i - mean_x) ** 2 for i in range(n))
        slope = num / den
        print(f"    task {row['id']}: n={n} OLS slope per month = {slope:.6f} "
              f"· per decade = {slope * 120:.6f} · per year = {slope * 12:.6f}")
        print(f"      check_spec keys: {sorted(check.keys())}")

print("\n=== 3. how many tasks in the pool are answerable with math-only compute? ===")
pool = conn.execute("SELECT domain, status, COUNT(*) n FROM tasks GROUP BY domain, status "
                    "ORDER BY domain, status").fetchall()
for row in pool:
    print(f"  {row['domain']:9} {row['status']:9} {row['n']}")
failed = conn.execute("SELECT task_id, answer, verdict, detail FROM submissions WHERE "
                      "verified=0 ORDER BY id DESC LIMIT 6").fetchall()
print("\n  recent failed submissions (what they actually answered):")
for row in failed:
    print(f"    task {row['task_id']:>3}  answer={str(row['answer'])[:60]:60} "
          f"{(row['detail'] or '')[:70]}")
conn.close()
