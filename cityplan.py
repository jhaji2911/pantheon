"""The town plan: streets, lots, houses, workstations, street furniture, trees and lamps.

Pantheon used to be civic buildings joined to the Agora by spokes, with every generated
object dropped on a golden-angle spiral. This module lays the town out the way towns are
laid out, deterministically, from the record the server already has:

  core       the civic buildings on a paved plaza (pedestrian; no carriageway)
  boulevard  a square ring road around the core, sidewalks both sides
  avenues    four axis roads from the boulevard out to the highway
  street     a second, residential ring
  highway    a rounded-square four-lane loop with a median barrier and guardrails

Generated assets keep their stored coordinates (provenance); the plan *sites* them: large
objects on lots facing the boulevard, benches and kiosks along its sidewalks, the car at a
kerb. Each resident gets a house on the residential ring, and a workstation at a desk inside
its workplace. Everything solid is also emitted as colliders, so navigation (navgrid.py)
and the visitor's controller (world3d.js) both respect it.
"""
from __future__ import annotations

import hashlib
import math
import random

# ---- geometry of the plan (world units) -----------------------------------------------
R1 = 34.0            # boulevard centreline (square ring half-size)
R1_W = 8.0           # boulevard carriageway width
R2 = 66.0            # residential street centreline
R2_W = 6.0
HW = 96.0            # highway centreline half-size (rounded square)
HW_R = 24.0          # highway corner radius
HW_W = 16.0          # both carriageways + median
AVE_W = 7.0
WALK = 2.2           # sidewalk width
BOUND = 110.0        # walkable square half-size
CORE_X, CORE_Z = 27.0, 19.0   # paved civic plaza half-extents

BUILDING_W, BUILDING_D = 7.4, 6.4
AGORA_W, AGORA_D = 9.0, 7.6
DOOR_HALF = 0.58
WALL = 0.22
HOUSE_W, HOUSE_D = 8.0, 7.0


def _box(x0, z0, x1, z1):
    return {"type": "box", "x0": round(min(x0, x1), 3), "z0": round(min(z0, z1), 3),
            "x1": round(max(x0, x1), 3), "z1": round(max(z0, z1), 3)}


def _circle(x, z, r):
    return {"type": "circle", "x": round(x, 3), "z": round(z, 3), "r": round(r, 3)}


def _rot(lx, lz, facing):
    """Local (x right, z toward the door) → world offset for a door facing `facing`."""
    return {"+z": (lx, lz), "-z": (-lx, -lz), "+x": (lz, -lx), "-x": (-lz, lx)}[facing]


def room(cx, cz, w, d, facing="+z"):
    """Walls of a w×d room centred at (cx, cz) with a door gap in the wall facing `facing`.
    Returns (colliders, opening) — the opening is a narrow corridor through the door."""
    hw, hd = w / 2, d / 2
    local = [(-hw, -hd, -hw + WALL, hd), (hw - WALL, -hd, hw, hd), (-hw, -hd - 0.1, hw, -hd + 0.12),
             (-hw, hd - 0.12, -DOOR_HALF, hd + 0.1), (DOOR_HALF, hd - 0.12, hw, hd + 0.1)]
    out = []
    for x0, z0, x1, z1 in local:
        ax, az = _rot(x0, z0, facing)
        bx, bz = _rot(x1, z1, facing)
        out.append(_box(cx + ax, cz + az, cx + bx, cz + bz))
    ax, az = _rot(-0.3, hd - 0.6, facing)
    bx, bz = _rot(0.3, hd + 0.6, facing)
    return out, _box(cx + ax, cz + az, cx + bx, cz + bz)


def building_size(pid):
    return (AGORA_W, AGORA_D) if pid == "agora" else (BUILDING_W, BUILDING_D)


# ---- streets ---------------------------------------------------------------------------
def _square(half):
    return [[-half, -half], [half, -half], [half, half], [-half, half], [-half, -half]]


def _rounded_square(half, r, per_corner=8):
    pts = []
    for cx, cz, a0 in ((half - r, half - r, 0), (-(half - r), half - r, 90),
                       (-(half - r), -(half - r), 180), (half - r, -(half - r), 270)):
        for i in range(per_corner + 1):
            a = math.radians(a0 + 90 * i / per_corner)
            pts.append([round(cx + r * math.cos(a), 2), round(cz + r * math.sin(a), 2)])
    pts.append(pts[0])
    return pts


def streets():
    out = [{"id": "boulevard", "kind": "boulevard", "width": R1_W, "closed": True, "points": _square(R1)},
           {"id": "residential", "kind": "street", "width": R2_W, "closed": True, "points": _square(R2)},
           {"id": "highway", "kind": "highway", "width": HW_W, "closed": True,
            "points": _rounded_square(HW, HW_R)}]
    inner, outer = R1, HW - HW_W / 2
    for name, a, b in (("north", [0, inner], [0, outer]), ("south", [0, -inner], [0, -outer]),
                       ("east", [inner, 0], [outer, 0]), ("west", [-inner, 0], [-outer, 0])):
        out.append({"id": "avenue-" + name, "kind": "avenue", "width": AVE_W, "closed": False, "points": [a, b]})
    # short connectors from the plaza to the boulevard along the avenue axes
    for name, a, b in (("north", [0, CORE_Z], [0, R1]), ("south", [0, -CORE_Z], [0, -R1]),
                       ("east", [CORE_X, 0], [R1, 0]), ("west", [-CORE_X, 0], [-R1, 0])):
        out.append({"id": "lane-" + name, "kind": "lane", "width": 5.0, "closed": False, "points": [a, b]})
    return out


def seg_dist(px, pz, a, b):
    ax, az = a
    bx, bz = b
    dx, dz = bx - ax, bz - az
    L2 = dx * dx + dz * dz or 1e-9
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / L2))
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def road_dist(x, z, roads, kinds=None):
    """Distance from (x, z) to the nearest road centreline (optionally of some kinds), and that road."""
    best = (math.inf, None)
    for r in roads:
        if kinds and r["kind"] not in kinds:
            continue
        for a, b in zip(r["points"], r["points"][1:]):
            d = seg_dist(x, z, a, b)
            if d < best[0]:
                best = (d, r)
    return best


# ---- lots along the square rings --------------------------------------------------------
def _side_slots(ring, offset, span_ns, span_ew, skip=6.5):
    """Frontage just outside the four sides of a square ring, `offset` from its centreline,
    every lot facing back toward the ring. North/south sides run the full `span_ns`; east/west
    stop at `span_ew` so corner lots never overlap."""
    edge = ring + offset
    return [{"side": side, "edge": edge, "facing": facing, "cursor": -span, "end": span, "skip": skip}
            for side, facing, span in (("north", "-z", span_ns), ("east", "-x", span_ew),
                                       ("south", "+z", span_ns), ("west", "+x", span_ew))]


def _place_on(side, w, d, gap=3.0):
    """Take the next free frontage on a side for a w (along street) × d (deep) footprint."""
    start = side["cursor"]
    if start < side["skip"] and start + w > -side["skip"]:   # keep clear of the avenue
        start = side["skip"]
    if start + w > side["end"]:
        return None
    side["cursor"] = start + w + gap
    along = start + w / 2
    depth = side["edge"] + d / 2
    s = side["side"]
    x, z = {"north": (along, depth), "south": (-along, -depth),
            "east": (depth, -along), "west": (-depth, along)}[s]
    return x, z, side["facing"]


def _footprint(w, d, facing):
    return (w, d) if facing in ("+z", "-z") else (d, w)


def plan(places, dynamic_places, assets, residents):
    """The whole town. `residents` are {name, home} rows (bodies)."""
    roads = streets()
    colliders, openings = [], []

    # civic buildings and their workstations
    workstations = []
    by_home = {}
    for r in sorted(residents, key=lambda r: r["name"].lower()):
        by_home.setdefault(r["home"], []).append(r["name"])
    for p in places:
        hx, hz = float(p["x"]), float(p["z"])
        w, d = building_size(p["id"])
        walls, door = room(hx, hz, w, d, "+z")
        colliders += walls
        openings.append(door)
        if p["id"] == "agora":
            colliders.append(_box(hx - 1.3, hz - 1.3, hx + 1.3, hz + 1.3))   # MIST monument
            continue
        if p["id"] == "hall":
            colliders.append(_circle(hx, hz, 1.28))                          # assembly table
            continue
        names = by_home.get(p["id"], [])
        slots = max(2, len(names))
        for i in range(slots):
            x = hx - (w / 2 - 1.1) + (w - 2.2) * (i / (slots - 1) if slots > 1 else 0.5)
            desk = {"x": round(x, 2), "z": round(hz - 1.75, 2)}
            colliders.append(_box(x - 0.7, hz - 2.12, x + 0.7, hz - 1.38))
            if i < len(names):
                workstations.append({"name": names[i], "place": p["id"], **desk,
                                     "chair": [round(x, 2), round(hz - 0.85, 2)], "facing": "+z"})

    for p in dynamic_places:                                                 # pavilions
        x, z = float(p["x"]), float(p["z"])
        colliders.append(_circle(x, z, 1.1))
        for i in range(6):
            a = i * math.pi / 3
            colliders.append(_circle(x + math.cos(a) * 2.85, z + math.sin(a) * 2.85, 0.14))

    # houses: one per resident, on the outer frontage of the residential ring, facing it
    houses = []
    house_off = R2_W / 2 + WALK + 0.8
    house_sides = _side_slots(R2, house_off, R2 + house_off + HOUSE_D + 5, R2 + house_off - 1)
    order = sorted(residents, key=lambda r: hashlib.sha256(r["name"].lower().encode()).hexdigest())
    for i, r in enumerate(order):
        for k in range(4):
            side = house_sides[(i + k) % 4]
            fw, fd = _footprint(HOUSE_W + 4, HOUSE_D + 5, side["facing"])     # house + yard
            got = _place_on(side, HOUSE_W + 4, HOUSE_D + 5, 2.0)
            if got:
                break
        if not got:
            continue
        lx, lz, facing = got
        # the house sits toward the street end of its yard
        ox, oz = _rot(0, 1.2, facing)
        cx, cz = lx + ox, lz + oz
        slug = "".join(c if c.isalnum() else "-" for c in r["name"].lower()).strip("-")
        walls, door = room(cx, cz, HOUSE_W, HOUSE_D, facing)
        colliders += walls
        openings.append(door)
        houses.append({"id": "house-" + slug, "name": r["name"] + "'s house", "owner": r["name"],
                       "kind": "house", "x": round(cx, 2), "z": round(cz, 2), "facing": facing,
                       "width": HOUSE_W, "depth": HOUSE_D,
                       "seed": int(hashlib.sha256(slug.encode()).hexdigest()[:6], 16)})

    # generated assets: big objects on boulevard lots, furniture on sidewalks, car at a kerb
    sited = []
    lot_off = R1_W / 2 + WALK + 1.0
    lot_sides = _side_slots(R1, lot_off, R2 - R2_W / 2 - WALK - 1, R1 + lot_off - 1)
    spill_sides = house_sides            # overflow continues on the residential ring's outer frontage
    furniture_spots = _sidewalk_spots(roads)
    lot_i = 0
    for a in sorted(assets, key=lambda a: (a.get("created") or 0, str(a["id"]))):
        kind, w, d = a["kind"], float(a["width"]), float(a["depth"])
        if kind == "street_furniture":
            if not furniture_spots:
                continue
            x, z, yaw = furniture_spots.pop(0)
            sited.append({"id": a["id"], "x": x, "z": z, "yaw": yaw})
            colliders.append(_box(x - w / 2, z - d / 2, x + w / 2, z + d / 2) if abs(math.sin(yaw)) < 0.5
                             else _box(x - d / 2, z - w / 2, x + d / 2, z + w / 2))
            continue
        if kind == "car":
            x, z = R2 - R2_W / 2 + 1.1, -18.0                    # parked at the east kerb, nose north
            sited.append({"id": a["id"], "x": round(x, 2), "z": round(z, 2), "yaw": 0.0})
            colliders.append(_box(x - w / 2, z - d / 2, x + w / 2, z + d / 2))
            continue
        long_side, short_side = max(w, d), min(w, d)
        got = None
        for pool in (lot_sides, spill_sides):
            for k in range(4):
                side = pool[(lot_i + k) % 4]
                got = _place_on(side, long_side, short_side)
                if got:
                    break
            if got:
                break
        lot_i += 1
        if not got:
            continue
        x, z, facing = got
        yaw = {"+z": 0.0, "-z": math.pi, "+x": math.pi / 2, "-x": -math.pi / 2}[facing]
        sited.append({"id": a["id"], "x": round(x, 2), "z": round(z, 2), "yaw": round(yaw, 4),
                      "facing": facing, "w": long_side, "d": short_side})
        if kind != "park":
            fw, fd = _footprint(long_side, short_side, facing)
            colliders.append(_box(x - fw / 2, z - fd / 2, x + fw / 2, z + fd / 2))

    # street trees and lamps along the sidewalks the furniture did not take
    trees, lamps = _street_trees_and_lamps(roads, furniture_spots, sited, houses)
    colliders += [_circle(t["x"], t["z"], 0.26) for t in trees]
    colliders += [_circle(l["x"], l["z"], 0.12) for l in lamps]
    return {"roads": roads, "colliders": colliders, "openings": openings, "houses": houses,
            "workstations": workstations, "sited": sited, "trees": trees, "lamps": lamps,
            "plaza": {"x": CORE_X, "z": CORE_Z}, "bound": BOUND}


def _sidewalk_spots(roads):
    """Bench/kiosk positions along the boulevard's outer sidewalk, facing the road."""
    spots = []
    # boulevard outer sidewalk (facing the boulevard), then the residential street's inner one
    for edge, reach, face_out in ((R1 + R1_W / 2 + WALK * 0.55, R1 + 3, False),
                                  (R2 - R2_W / 2 - WALK * 0.55, R2 - 4, True)):
        flip = math.pi if face_out else 0.0
        for i in range(-int(reach) // 7, int(reach) // 7 + 1):
            t = i * 7.0 + 3.5
            if abs(t) < 6.5 or abs(t) > reach:
                continue
            spots += [(round(t, 2), round(edge, 2), math.pi + flip), (round(edge, 2), round(-t, 2), -math.pi / 2 + flip),
                      (round(-t, 2), round(-edge, 2), 0.0 + flip), (round(-edge, 2), round(t, 2), math.pi / 2 + flip)]
    # interleave sides so a short list still spreads round the town
    return sorted(spots, key=lambda s: (abs(s[0]) + abs(s[1])) % 13 + math.atan2(s[1], s[0]) * 0.001)


def _street_trees_and_lamps(roads, free_spots, sited, houses):
    rng = random.Random(7_311)
    trees, lamps = [], []
    taken = [(s["x"], s["z"]) for s in sited] + [(h["x"], h["z"]) for h in houses]

    def clear(x, z, r):
        return all(math.hypot(x - tx, z - tz) > r for tx, tz in taken)

    for road in roads:
        if road["kind"] == "highway":
            continue
        off = road["width"] / 2 + WALK * 0.5
        step = 14.0 if road["kind"] != "lane" else 99
        for a, b in zip(road["points"], road["points"][1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if not L:
                continue
            ux, uz = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            nx, nz = -uz, ux
            d = 5.0
            while d < L - 4:
                for side in (-1, 1):
                    x, z = a[0] + ux * d + nx * off * side, a[1] + uz * d + nz * off * side
                    if abs(x) < CORE_X + 1 and abs(z) < CORE_Z + 1:
                        continue
                    if (road["kind"] == "boulevard" and side == 1) or not clear(x, z, 4.5):
                        continue
                    near, other = road_dist(x, z, roads)          # junctions: clear every carriageway
                    if near < other["width"] / 2 + 0.6:
                        continue
                    if int(d / step) % 2 == 0:
                        lamps.append({"x": round(x, 2), "z": round(z, 2),
                                      "yaw": round(math.atan2(-nx * side, -nz * side), 3)})
                    else:
                        trees.append({"x": round(x, 2), "z": round(z, 2), "h": round(3.6 + rng.random() * 1.6, 2),
                                      "seed": rng.randrange(1 << 30)})
                    taken.append((x, z))
                d += step / 2
    # woodland beyond the highway
    for _ in range(90):
        x, z = (rng.random() - 0.5) * 2 * (BOUND - 3), (rng.random() - 0.5) * 2 * (BOUND - 3)
        if max(abs(x), abs(z)) < HW + HW_W / 2 + 3:
            continue
        if not clear(x, z, 3.5):
            continue
        trees.append({"x": round(x, 2), "z": round(z, 2), "h": round(4 + rng.random() * 2.5, 2),
                      "seed": rng.randrange(1 << 30)})
        taken.append((x, z))
    return trees, lamps
