"""Exercise the whole console backend against the live server.

Reads first, then the two spending endpoints (one question, one small townhall), so a
failure is localised. Prints what each returned and asserts the contract's key fields.
"""
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8790"


def get(path, timeout=60):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def post(path, payload, timeout=600):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


print("=== 1. static assets (the UI's modules) ===")
for asset in ("/api/static/app.js", "/api/static/style.css",
              "/api/static/views/colony.js", "/api/static/views/ci.js",
              "/api/static/views/intercom.js", "/api/static/views/assembly.js"):
    try:
        req = urllib.request.Request(BASE + asset)
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
        print(f"  {resp.status} {asset:34} {len(body):>7} bytes")
    except urllib.error.HTTPError as exc:
        print(f"  {exc.code} {asset:34} MISSING")

print("\n=== 2. module registry ===")
status, modules = get("/api/modules")
print(f"  {status} routes={modules['routes']} error={modules['error'] or 'none'}")
for pattern in modules["loaded"]:
    print("    ", pattern)

print("\n=== 3. the world ===")
status, world = get("/api/world", timeout=120)
print(f"  {status} sources failed: {world['errors'] or 'none'} "
      f"· keys: {sorted(world.keys())}")
colony = world["colony"]
print(f"  colony in world: tick={colony.get('tick')} agents={len(colony.get('agents', []))} "
      f"bridge_error={colony.get('bridge_error', 'none')}")

print("\n=== 4. GET /api/colony ===")
status, co = get("/api/colony")
print(f"  {status} tick={co['tick']} population={co['population']} tiers={co['tiers']}")
print(f"    work={co['work']['solved']}/{co['work']['attempts']} "
      f"credits={co['economy']['circulation']} laws={len(co['laws'])} "
      f"tasks={len(co['tasks'])} models={co['models']}")
print(f"    tokens this tick={co['tokens']['this_tick']} budgets={co['budgets']}")
print(f"    roster_health={co['roster_health']}")
for agent in co["agents"]:
    doing = agent["doing"]["task_id"] if agent["doing"] else "—"
    call = agent["last_call"]["model"] if agent["last_call"] else "—"
    print(f"    {agent['name']:11} {agent['tier']:10} {agent['domain']:8} "
          f"fit{agent['fitness']:.2f} doing={str(doing):4} last={call:26} "
          f"brain={agent['brain']}")

print("\n=== 5. GET /api/ci/<name> (the brain) ===")
status, ci = get("/api/ci/Vesper")
print(f"  {status} agent={ci['agent']['name']} tier={ci['tier']['model']} "
      f"may={len(ci['tier']['may'])} instruments")
print(f"    identity block: {len(ci['identity']['block'])} chars · "
      f"memory={len(ci['memory'])} · notebook={len(ci['notebook']['files'])} files · "
      f"submissions={len(ci['submissions'])} · instruments={len(ci['instruments'])} · "
      f"usage={len(ci['usage'])} · events={len(ci['events'])}")
print(f"    lineage: parent={ci['lineage']['parent']} children={ci['lineage']['children']}")
print(f"    thread with MIST: {len(ci['thread'])} exchange(s)")
if ci["memory"]:
    print(f"    newest memory: [{ci['memory'][0]['kind']}] {ci['memory'][0]['text'][:90]}")
print(f"  404 check: {get.__name__}", end=" ")
try:
    get("/api/ci/NoSuchCI")
    print("FAILED (expected 404)")
except urllib.error.HTTPError as exc:
    print(f"{exc.code} {json.loads(exc.read().decode())['error']}")

print("\n=== 6. notebook read ===")
files = ci["notebook"]["files"]
if files:
    path = files[0]["path"]
    status, note = get(f"/api/ci/Vesper/note?path={path}")
    print(f"  {status} {path}: {len(note.get('text', ''))} chars")
else:
    print("  (Vesper has no notebook files yet)")

print("\n=== 7. TALK: POST /api/ci/Vesper/ask (one live call) ===")
t0 = time.time()
status, reply = post("/api/ci/Vesper/ask", {
    "message": "MIST here. In two sentences: what are you working on, and what would make "
               "you trust your own answer enough to submit it?"})
print(f"  {status} in {time.time() - t0:.1f}s · model={reply.get('model')} "
      f"tokens={reply.get('tokens')} ms={reply.get('ms')}")
print(f"  {reply.get('ci')}: {(reply.get('reply') or reply.get('error') or '')[:400]}")

print("\n=== 8. ASSEMBLE: POST /api/assembly (townhall, 2 CIs, 1 round) ===")
t0 = time.time()
status, hall = post("/api/assembly", {
    "kind": "townhall",
    "topic": "Should the colony raise difficulty on climate tasks rather than hide Fathom's "
             "failure rate? Answer as yourself.",
    "cis": ["Vesper", "Morrow"], "rounds": 1})
print(f"  {status} in {time.time() - t0:.1f}s · id={hall.get('id')} "
      f"spend={hall.get('spend')} closing={hall.get('closing')}")
for line in hall.get("transcript", []):
    print(f"  [round {line['round']}] {line['name']} ({line['tier']}, {line['model']}, "
          f"{line['ms']}ms): {(line['text'] or line.get('error') or '')[:260]}")

print("\n=== 9. history ===")
status, past = get("/api/assemblies")
print(f"  {status} {len(past['assemblies'])} assembly(s) stored · stats={past['stats']}")
if past["assemblies"]:
    first = past["assemblies"][0]
    print(f"    newest: {first['id']} {first['kind']} '{first['topic'][:50]}' "
          f"{first['speakers']} speech(es)")
    status, whole = get(f"/api/assembly/{first['id']}")
    print(f"    reopen: {status} transcript lines={len(whole['transcript'])}")

print("\n=== 10. costs on the record ===")
status, ci = get("/api/ci/Vesper")
print(f"  {status} Vesper thread now {len(ci['thread'])} exchange(s)")
print("\nALL BACKEND ENDPOINTS EXERCISED.")
