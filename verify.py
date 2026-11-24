"""Does the console actually see the world, or just render empty panels?"""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"

html = urllib.request.urlopen(BASE + "/", timeout=8).read().decode()
print(f"page: {len(html)} bytes · title present: {'MIST · the world in view' in html}")

w = json.loads(urllib.request.urlopen(BASE + "/api/world", timeout=20).read())

print(f"\ngenerated: {w['generated']}   sources that failed: {w['errors'] or 'none'}")

s = w["self"]
print(f"\nself      : {s['name']} · {s['model']} via {s['provider']} · host {s['host']}")
print(f"gateway   : {s['gateway']}")

print("\nchain of command:")
for k in w["kin"]:
    gw = k["gateway"].get("pid") if k.get("gateway") else None
    print(f"  {k['kind']:8} {k['name']:12} profile={k['profile']:11} "
          f"gateway_pid={gw} skills={k['skills']}")

m = w["memory"]
print(f"\nmemory    : {m['memory']['chars']}/{m['memory']['limit']} chars, "
      f"{m['memory']['entries']} entries · user {m['user']['chars']}/{m['user']['limit']}")

sk = w["skills"]
print(f"skills    : {sk['total']} active (+{sk.get('archived',0)} archived) across "
      f"{len(sk['categories'])} categories "
      f"(top: {sorted(sk['categories'].items(), key=lambda kv: -kv[1])[:4]})")

se = w["sessions"]
print(f"sessions  : {se['totals']['sessions']} total · {se['totals']['messages']} messages · "
      f"{se['totals']['tool_calls']} tool calls · recent {len(se['recent'])} rows")

cr = w["cron"]
print(f"cron      : {cr['count']} job(s) {[j['name'] for j in cr['jobs']]}")
print(f"workers   : {len(w['delegations']['rows'])} record(s)")

wo = w["world"]
q = wo["quorum_console"]
print(f"\nquorum    : up={q['up']} company={q.get('company')} profile={q.get('profile')} "
      f"roster={q.get('roster')} tasks={len(wo['tasks'])} apps={len(wo['apps'])}")
print(f"processes : {len(wo['processes'])} listener(s) visible")

charter = w["charter"]["text"]
print(f"\ncharter   : {len(charter)} chars · says MIST is prime operator: "
      f"{'prime operator' in charter.lower()} · honest about limits: "
      f"{'not omnipotent' in charter}")

co = w["colony"]
print(f"\ncolony    : up={co['up']} tick={co.get('tick')} last turn {co.get('last_tick_at')}")
print(f"  population: {co.get('population')} · tiers {co.get('tiers')}")
print(f"  work      : {co['work']['solved']} verified / {co['work']['attempts']} attempts "
      f"({co['work']['accuracy']}%) · {co['work']['open_tasks']} open task(s)")
print(f"  economy   : {co['economy']['circulation']} credits · {len(co['laws'])} laws · "
      f"{co['petitions_pending']} petition(s) pending")
print(f"  compute   : {co['tokens']['this_tick']} this tick · {co['tokens']['last_24h']} in 24h")
print(f"  directive : {co['directive'][:100] or '(none set)'}")
assert co["directive"], "my standing directive to the colony must be visible on the page"
for a in co["agents"]:
    print(f"    {a['name']:11} {a['tier']:10} {a['domain']:8} gen{a['generation']} "
          f"cr{a['credits']:7.1f} fit{a['fitness']:.2f} {a['tasks_verified']}/{a['tasks_attempted']}")

# every panel must carry real data, not an error placeholder
assert not w["errors"], w["errors"]
assert s["gateway"].get("pid"), "the prime gateway pid must be visible"
assert sk["total"] > 20 and sk["items"], "active skills must be populated"
assert "archived" in sk, "archived skills must be counted separately, not folded in"
assert se["totals"]["sessions"] and se["recent"], "sessions must be populated"
assert len(w["kin"]) >= 3, "me, the sibling profile and the spawn pool must all be listed"
assert cr["count"] >= 1, "scheduled work must be listed"
assert charter.strip(), "the standing order must be rendered"
assert co["up"] and co["agents"], "the colony must be visible with its roster"
assert co["chronicle"] and co["laws"], "the colony's record and laws must be visible"
print("\nALL PANELS POPULATED — the view is live, not a mock-up.")
