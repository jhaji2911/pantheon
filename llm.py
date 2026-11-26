"""Model routing for resident minds: free OpenCode Go models first, inferN's local models second.

  cloud   the colony's OpenCode Go relay, on the resident's own colony tier model (the
          colony runs on the Go plan's free, unlimited models). A response is accepted only
          when OpenCode reports Go billing with zero cost, zero list cost and zero allowance
          drawn — free calls that never eat into the Go plan. Anything else is refused.
  local   the inferN cell (Aetherion, `POST /mesh/infer`) with privacy "mesh": served by an
          on-device provider of this node or a paired peer, never a cloud one. The console
          never starts it: it is available only while the inferN app's server switch is on.

`think(kind, ...)` tries the routes in order and falls back on failure or an unusable reply,
so an OpenCode outage degrades to inferN while the app has it running. Each result names the
provider, model and locality that actually served it.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import bridge  # noqa: F401  (puts the colony package on sys.path)
from colony import transport

INFERN_URL = os.environ.get("MIST_INFERN_URL", "http://127.0.0.1:8080").rstrip("/")
ROUTES = {
    "moment": ("cloud", "local"),     # what to do right now
    "converse": ("cloud", "local"),   # replying to someone who spoke to you
    "plan": ("cloud", "local"),       # the day's plan
    "reflect": ("cloud", "local"),    # turning episodes into insight
}


STANDALONE = bool(getattr(transport, "STANDALONE", False))
PROVIDER = "openai-compatible" if STANDALONE else "opencode-go"


def free_go(usage: dict) -> bool:
    """True only for a Go-billed call that cost nothing and drew nothing from the plan."""
    oc = (usage or {}).get("opencode") or {}
    return (oc.get("billing_source") == "go" and float((usage or {}).get("cost") or 0) == 0
            and float(oc.get("list_cost") or 0) == 0 and float(oc.get("allowance") or 0) == 0)


def billing_ok(usage: dict) -> bool:
    """Standalone calls go to an endpoint you chose yourself, so there is no plan to protect."""
    return STANDALONE or free_go(usage)


def _local(system, user, schema, max_tokens, temperature, timeout):
    body = {"prompt": user, "system": system, "privacy": "mesh", "retrieve": False,
            "temperature": temperature, "max_output_tokens": max_tokens}
    if schema:
        body["format"] = schema
    req = urllib.request.Request(INFERN_URL + "/mesh/infer", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("message") or str(exc)
        except Exception:                                        # noqa: BLE001
            msg = str(exc)
        return {"ok": False, "error": "inferN: " + msg[:240], "locality": "local"}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "error": "inferN unreachable at %s: %s" % (INFERN_URL, exc), "locality": "local"}
    served = out.get("served_by") or {}
    text = out.get("text") or ""
    return {"ok": True, "text": text, "model": served.get("model") or "local",
            "provider": "inferN/" + (served.get("provider_id") or "?"),
            "node": served.get("node_name"), "locality": "local",
            "tokens": (len(system) + len(user) + len(text)) // 4,   # estimate; not billed
            "ms": out.get("latency_ms") or int((time.time() - started) * 1000)}


def _cloud(model, system, user, max_tokens, temperature, relay):
    relay = relay or transport.Relay()
    result = relay.chat(model, [{"role": "system", "content": system},
                                      {"role": "user", "content": user}],
                        max_tokens=max_tokens, temperature=temperature, tier="worker")
    usage = result.get("usage") or {}
    base = {"locality": "cloud", "model": result.get("model") or model, "provider": PROVIDER,
            "ms": result.get("ms"),
            "tokens": int(usage.get("total_tokens") or
                          (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))}
    if not result.get("ok"):
        return {**base, "ok": False, "error": result.get("error") or "relay call failed"}
    if not billing_ok(usage):
        return {**base, "ok": False, "error": "refused: OpenCode did not confirm a free Go call "
                "(zero cost, list cost and allowance)"}
    return {**base, "ok": True, "text": result.get("content") or ""}


def think(kind, system, user, model, schema=None, max_tokens=700, temperature=0.5,
          relay=None, local=None, allow_cloud=True, timeout=90, validate=None):
    """Run one thought on the preferred route for `kind`, falling back to the other.

    `validate(text)` turns the reply into the caller's value or raises; an unusable reply
    counts as that route failing, so the next route gets the question (the local route
    decodes against `schema`, so it is the dependable fallback for structure). The result
    carries `value` when a validator was given. `local` replaces the inferN call (tests);
    `allow_cloud=False` keeps it local-only (e.g. when the daily cloud budget is spent).
    `attempts` lists every route tried."""
    attempts, last = [], {"locality": None, "model": None, "tokens": 0, "ms": None}
    for route in ROUTES.get(kind, ROUTES["moment"]):
        if route == "cloud" and not allow_cloud:
            attempts.append({"route": "cloud", "error": "cloud budget spent"})
            continue
        if route == "local":
            out = (local or _local)(system, user, schema, max_tokens, temperature, timeout)
        else:
            out = _cloud(model, system, user, max_tokens, temperature, relay)
        if out["ok"] and validate is not None:
            try:
                out["value"] = validate(out["text"])
            except Exception as exc:                              # noqa: BLE001
                out = {**out, "ok": False, "error": "%s reply unusable: %s" % (route, exc)}
        attempts.append({"route": route, "ok": out["ok"], "error": out.get("error")})
        if out["ok"]:
            return {**out, "attempts": attempts}
        last = out
    return {**last, "ok": False, "error": "; ".join(a["error"] for a in attempts if a.get("error")),
            "attempts": attempts}
