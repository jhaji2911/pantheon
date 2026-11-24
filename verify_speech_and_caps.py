"""Two questions at once:

A) After the speech-cap fix, do assembly speeches come out as complete sentences?
B) In real colony work, are the tier token caps truncating the CIs mid-thought?
   (a completion hitting exactly the tier's max_tokens is a truncation signal)
"""
import json
import pathlib
import sqlite3
import time
import urllib.request

BASE = "http://127.0.0.1:8790"
DB = pathlib.Path.home() / "Code" / "colony" / "data" / "colony.db"
CAPS = {"reflex": 320, "worker": 600, "specialist": 900, "architect": 1200}


def post(path, payload, timeout=900):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


print("=== A. dinner, three CIs, one round (after the cap fix) ===")
t0 = time.time()
hall = post("/api/assembly", {
    "kind": "dinner",
    "topic": "Fathom has failed the same climate task twice and has zero fitness. "
             "What should the table do about it?",
    "cis": ["Vesper", "Kestrel", "Fathom"], "rounds": 1})
print(f"  {hall['id']} in {time.time() - t0:.1f}s · spend={hall['spend']}\n")
for line in hall["transcript"]:
    text = line["text"] or ""
    finished = text.rstrip().endswith((".", "!", "?", '"', ")"))
    print(f"  {line['name']:10} {line['tier']:10} {line['ms']:>6}ms "
          f"{line['tokens']:>5}tok  complete={finished}  chars={len(text)}")
    print(f"     {text[:420]}")
    print()

print("=== B. are the tier caps truncating colony work? ===")
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT tick, tier, model, COUNT(*) calls,
           SUM(CASE WHEN completion_tokens >= ? AND tier='reflex' THEN 1
                    WHEN completion_tokens >= ? AND tier='worker' THEN 1
                    WHEN completion_tokens >= ? AND tier='specialist' THEN 1
                    WHEN completion_tokens >= ? AND tier='architect' THEN 1
                    ELSE 0 END) at_cap
      FROM usage GROUP BY tick, tier, model ORDER BY tick DESC, tier""",
    (CAPS["reflex"], CAPS["worker"], CAPS["specialist"], CAPS["architect"])).fetchall()
print(f"  {'tick':>4} {'tier':10} {'model':26} {'calls':>5} {'at_cap':>6}  share")
for r in rows:
    share = f"{100.0 * (r['at_cap'] or 0) / r['calls']:.0f}%" if r["calls"] else "-"
    print(f"  {r['tick']:>4} {r['tier']:10} {str(r['model']):26} {r['calls']:>5} "
          f"{str(r['at_cap'] or 0):>6}  {share}")

print("\n  tick 5 outcome, from the record:")
for kind, count in conn.execute("SELECT kind, COUNT(*) FROM events WHERE tick=5 "
                                "GROUP BY kind ORDER BY 2 DESC"):
    print(f"    {kind:16} {count}")
conn.close()
