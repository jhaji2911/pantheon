"""Vinod Chanda's bounded, persistent Pantheon asset builder.

The model proposes a compact design; this module validates it, assigns a collision-free
site inside the world bounds, and persists it in the MIST Console database. Model prose
never controls filesystem paths, code, or coordinates outside the validator.
"""
from __future__ import annotations

import json
import hashlib
import math
import re
import threading
import time
import uuid

from bridge import Record
from colony import settings, transport
import llm
import pantheon
import store

OWNER = "Vinod Chanda"
PROFILE = "cc-operator"
MODEL = "deepseek-v4.1-flash"  # cc-operator's OpenCode Go model; live probe returned cost=0
KINDS = {"car", "building", "bridge", "park", "sculpture", "street_furniture"}
MAX_ASSETS = 250
AUTO_BUILD_INTERVAL = 900.0

_lock = threading.Lock()
_started = False
_last_build = 0.0
_build_state = "idle"
_last_build_result = None
_last_build_error = ""

SYSTEM_PROMPT = (
    "You are Vinod Chanda, Hermes profile cc-operator, the owner and steward of MIST's "
    "living 3D world asset builder. Given the residents' real recorded work, design ONE "
    "useful real-world object for their town. Output only a compact JSON object with keys "
    "kind, name, description, color, width, depth, height. kind must be one of: car, "
    "building, bridge, park, sculpture, street_furniture. color is six-digit hex. Dimensions "
    "are world units. No coordinates. Keep the name under 40 chars and description under "
    "140 chars. No markdown or extra keys."
)


def _text(value, limit, field):
    if not isinstance(value, str):
        raise ValueError("%s must be text" % field)
    value = " ".join(value.split()).strip()
    if not value or len(value) > limit:
        raise ValueError("%s must be 1..%d characters" % (field, limit))
    return value


def validate_design(raw):
    if not isinstance(raw, dict):
        raise ValueError("model response must be a JSON object")
    kind = str(raw.get("kind", "")).strip().lower()
    if kind not in KINDS:
        raise ValueError("unsupported asset kind")
    name = _text(raw.get("name"), 48, "name")
    description = _text(raw.get("description"), 180, "description")
    color = raw.get("color")
    if not isinstance(color, str) or not color.strip():
        raise ValueError("color is required")
    color = color.strip().lower()
    if re.fullmatch(r"[0-9a-f]{6}", color):
        color = "#" + color
    if not re.fullmatch(r"#[0-9a-f]{6}", color):
        # Models sometimes emit a color name despite the hex instruction. Map names
        # deterministically to a bounded palette; never pass arbitrary text to the renderer.
        palette = ("#8ba4a8", "#b5aa91", "#657579", "#92785b", "#536d65",
                   "#9b6c58", "#647b91", "#74756a", "#b09b67", "#5b5e6b")
        if not re.fullmatch(r"[a-z][a-z -]{0,30}", color):
            raise ValueError("color must be a hex value or plain color name; got %r" % color[:48])
        color = palette[int.from_bytes(hashlib.sha256(color.encode("utf-8")).digest()[:2], "big") % len(palette)]
    limits = {"car": (1.4, 5.5, 1.2, 3.2, 0.8, 3.5),
              "building": (3, 18, 3, 18, 3, 20),
              "bridge": (3, 24, 2, 10, 1, 8),
              "park": (4, 24, 4, 24, 0.2, 3),
              "sculpture": (0.6, 6, 0.6, 6, 1, 12),
              "street_furniture": (0.4, 4, 0.4, 4, 0.4, 5)}[kind]
    dimensions = []
    for key, low, high in zip(("width", "depth", "height"), limits[::2], limits[1::2]):
        try:
            value = float(raw.get(key))
        except (TypeError, ValueError):
            raise ValueError("%s must be numeric" % key)
        if not math.isfinite(value):
            raise ValueError("%s must be finite" % key)
        # Model dimensions are proposals, not trusted renderer values. Clamp them to
        # the per-kind envelope so a lively but over-wide design stays safe to render.
        value = max(low, min(high, value))
        dimensions.append(round(value, 2))
    return {"kind": kind, "name": name, "description": description,
            "color": color.lower(), "width": dimensions[0],
            "depth": dimensions[1], "height": dimensions[2]}


def _extract_json(text):
    text = text or ""
    start = text.find("{")
    if start < 0:
        raise ValueError("model returned no JSON object")
    depth, quoted, escaped = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if quoted:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                quoted = False
            continue
        if c == '"':
            quoted = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("model JSON was truncated")


def _allocate_site(design, existing_places=None, existing_assets=None):
    places = list(existing_places if existing_places is not None else store.world_places())
    places.extend({"x": p["x"], "z": p["z"], "width": 8, "depth": 8}
                  for p in pantheon.PLACES.values())
    assets = list(existing_assets if existing_assets is not None else store.world_assets(MAX_ASSETS))
    # Deterministic expanding golden-angle search. Keep every generated object on the
    # ground disk and clear of current buildings/previous assets by their actual footprint.
    base_radius = 31.0
    for idx in range(600):
        angle = idx * 2.399963229728653
        radius = min(62.0, base_radius + 0.24 * idx)
        x, z = round(math.cos(angle) * radius, 2), round(math.sin(angle) * radius, 2)
        margin = max(design["width"], design["depth"]) / 2 + 2.0
        if any(math.hypot(x - float(p["x"]), z - float(p["z"])) <
               margin + max(float(p.get("width", 0)), float(p.get("depth", 0))) / 2
               for p in places):
            continue
        if any(math.hypot(x - float(a["x"]), z - float(a["z"])) <
               margin + max(float(a["width"]), float(a["depth"])) / 2
               for a in assets):
            continue
        return x, z
    raise ValueError("no safe placement found; world is full")


def create_asset(brief, record=None, relay=None):
    """Generate, validate and persist one asset; called only on explicit or scheduled work."""
    brief = _text(brief, 500, "brief")
    if len(store.world_assets(MAX_ASSETS)) >= MAX_ASSETS:
        return {"error": "world asset cap reached", "status": 409}
    record = record or Record()
    latest = record.q("SELECT tick, kind, text FROM events ORDER BY id DESC LIMIT 5")
    residents = record.q("SELECT name, tier, domain, status FROM agents "
                         "WHERE status!='retired' ORDER BY name LIMIT 16")
    context = {"tick": record.tick(), "recent_record": latest, "residents": residents}
    relay = relay or transport.Relay()
    result = relay.chat(MODEL, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Build brief: %s\n\nCurrent world record (use for context only): %s\n\nReturn JSON only." %
         (brief, json.dumps(context, ensure_ascii=False)[:3200])},
    ], max_tokens=420, temperature=0.45, tier="worker")
    if not result.get("ok"):
        return {"error": result.get("error") or "OpenCode model call failed", "status": 502,
                "model": result.get("model") or MODEL}
    usage = result.get("usage") or {}
    billing = usage.get("opencode") or {}
    model_cost = float(usage.get("cost") or 0)
    if not llm.STANDALONE and (model_cost != 0 or billing.get("billing_source") != "go"):
        return {"error": "asset build refused: OpenCode did not confirm zero-cost Go billing",
                "status": 502, "model": result.get("model") or MODEL,
                "billing_source": billing.get("billing_source"), "cost": model_cost}
    try:
        design = validate_design(_extract_json(result.get("content")))
        x, z = _allocate_site(design)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"error": "asset design rejected: %s" % exc, "status": 502,
                "model": result.get("model") or MODEL}
    asset = {
        "id": uuid.uuid4().hex[:16], "owner": OWNER, "owner_profile": PROFILE,
        **design, "x": x, "z": z,
        "model": result.get("model") or MODEL,
        "billing_source": ((usage.get("opencode") or {}).get("billing_source") or "unknown"),
        "cost": float(usage.get("cost") or 0),
        "tokens": int(usage.get("total_tokens") or 0),
        "brief": brief, "created": time.time(),
        "source_tick": context["tick"],
        "source_event_ids": [int(e.get("id", 0)) for e in latest if e.get("id") is not None],
    }
    saved = store.create_world_asset(asset)
    return {"asset": saved, "model": asset["model"], "cost": asset["cost"],
            "tokens": asset["tokens"], "status": 201}


def _auto_brief(record):
    events = record.q("SELECT kind, text FROM events WHERE kind IN ('verified','failed','task_authored','promoted','demoted') "
                      "ORDER BY id DESC LIMIT 4")
    if events:
        evidence = "; ".join("%s: %s" % (e["kind"], e["text"][:100]) for e in events)
        return "Extend the town with one useful real-world asset inspired by the residents' recent life: " + evidence
    return "Start the town's material life with a useful everyday vehicle, civic building, or public place for the resident intelligences."


def _auto_loop():
    global _last_build
    while True:
        try:
            with _lock:
                _last_build = time.time()
            record = Record()
            # A resident's own request (minds.py `request_asset`) outranks the
            # builder's reading of the record.
            request = store.next_asset_request()
            if request:
                brief = "Requested by resident %s: %s" % (request["name"], request["brief"])
                out = create_asset(brief[:500], record=record)
                asset = out.get("asset")
                store.finish_asset_request(request["id"], "built" if asset else "rejected",
                                           asset["id"] if asset else None)
                store.remember(request["name"], "builder",
                               ("Vinod built my request: %s" % asset["name"]) if asset else
                               ("Vinod could not build my request: %s" % out.get("error", "rejected")),
                               0.7)
            else:
                create_asset(_auto_brief(record), record=record)
        except Exception:
            pass
        time.sleep(AUTO_BUILD_INTERVAL)


def start_autobuilder():
    """Start the world-owned background generator once; first asset is built immediately."""
    global _started
    with _lock:
        if _started:
            return False
        _started = True
    threading.Thread(target=_auto_loop, name="vinod-world-builder", daemon=True).start()
    return True


def builder_status():
    return {"owner": OWNER, "profile": PROFILE, "model": MODEL,
            "assets": store.world_assets(MAX_ASSETS), "interval_seconds": AUTO_BUILD_INTERVAL,
            "autobuilder_started": _started, "last_build_started": _last_build}


def _assets(match, query, body):
    return 200, builder_status()


def _build(match, query, body):
    body = body or {}
    brief = (body.get("brief") or "").strip()
    try:
        out = create_asset(brief)
    except Exception as exc:
        return 502, {"error": "%s: %s" % (type(exc).__name__, exc)}
    status = int(out.pop("status", 200 if not out.get("error") else 502))
    return status, out


import re
ROUTES = [
    ("GET", re.compile(r"^/api/world-builder$"), _assets),
    ("POST", re.compile(r"^/api/world-builder/build$"), _build),
]
