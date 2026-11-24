"""Navigation for Pantheon bodies: A* over the town plan's walkable ground.

The town's solid geometry comes from cityplan.py as colliders (axis-aligned boxes and
circles): building and house walls with real door gaps, desks, the Hall table, the MIST
monument, pavilion posts, sited assets, tree trunks and lamp posts. The server routes every
resident's journey through it, and the client receives the same colliders for the visitor's
own character controller, so nobody — resident or visitor — walks through a wall.

Routing is A* on a 0.5-unit grid with obstacles inflated by a body radius and octile moves.
Pedestrians prefer sidewalks and the paved plaza, may cross a carriageway at a cost, walk on
grass reluctantly, and never walk on the highway. The cell path is shortened only where a
straight segment is both unobstructed and no more expensive, so a resident keeps to the
sidewalk instead of cutting across lawns and roads.
"""
from __future__ import annotations

import heapq
import math

import cityplan

CELL = 0.5
EXTENT = cityplan.BOUND + 4       # grid covers [-EXTENT, EXTENT] on x and z
N = int(2 * EXTENT / CELL)
BODY_R = 0.35                     # obstacle inflation: a resident's shoulder radius
COST = {"walk": 1.0, "grass": 1.5, "road": 2.4}

BUILDING_W, BUILDING_D = cityplan.BUILDING_W, cityplan.BUILDING_D
DOOR_HALF = cityplan.DOOR_HALF
_seg_dist = cityplan.seg_dist


def layout(places, dynamic_places, assets, residents=()):
    """The town plan (cityplan.plan) — roads, lots, houses, workstations and colliders."""
    return cityplan.plan(list(places), list(dynamic_places), list(assets), list(residents))


def _cell(v):
    return max(0, min(N - 1, int((v + EXTENT) / CELL)))


def _centre(i):
    return -EXTENT + (i + 0.5) * CELL


class NavGrid:
    def __init__(self, lay):
        self.layout = lay
        self.blocked = bytearray(N * N)
        self.cost = [COST["grass"]] * (N * N)
        bound = lay.get("bound", cityplan.BOUND)
        for j in range(N):
            z = _centre(j)
            for i in range(N):
                if max(abs(_centre(i)), abs(z)) > bound:
                    self.blocked[j * N + i] = 1
        px, pz = lay["plaza"]["x"], lay["plaza"]["z"]
        self._fill(-px, -pz, px, pz, COST["walk"])
        for road in lay["roads"]:
            half = road["width"] / 2
            for a, b in zip(road["points"], road["points"][1:]):
                self._band(a, b, half + cityplan.WALK, COST["walk"], road["kind"] == "highway")
                if road["kind"] != "highway":
                    self._band(a, b, half, COST["road"], False)
        for c in lay["colliders"]:
            self._rasterise(c)
        for o in lay.get("openings", ()):
            for j in range(_cell(o["z0"]), _cell(o["z1"]) + 1):
                for i in range(_cell(o["x0"]), _cell(o["x1"]) + 1):
                    if o["x0"] <= _centre(i) <= o["x1"] and o["z0"] <= _centre(j) <= o["z1"]:
                        self.blocked[j * N + i] = 0

    def _fill(self, x0, z0, x1, z1, cost):
        for j in range(_cell(z0), _cell(z1) + 1):
            for i in range(_cell(x0), _cell(x1) + 1):
                self.cost[j * N + i] = cost

    def _band(self, a, b, half, cost, block):
        """Mark cells within `half` of segment a→b: a cost, or blocked (the highway)."""
        for j in range(_cell(min(a[1], b[1]) - half), _cell(max(a[1], b[1]) + half) + 1):
            z = _centre(j)
            for i in range(_cell(min(a[0], b[0]) - half), _cell(max(a[0], b[0]) + half) + 1):
                if _seg_dist(_centre(i), z, a, b) <= half:
                    if block:
                        self.blocked[j * N + i] = 1
                    else:
                        self.cost[j * N + i] = cost

    def _rasterise(self, c):
        r = BODY_R
        if c["type"] == "box":
            x0, z0, x1, z1 = c["x0"] - r, c["z0"] - r, c["x1"] + r, c["z1"] + r
            for j in range(_cell(z0), _cell(z1) + 1):
                for i in range(_cell(x0), _cell(x1) + 1):
                    x, z = _centre(i), _centre(j)
                    if x0 <= x <= x1 and z0 <= z <= z1:
                        self.blocked[j * N + i] = 1
        else:
            rr = c["r"] + r
            for j in range(_cell(c["z"] - rr), _cell(c["z"] + rr) + 1):
                for i in range(_cell(c["x"] - rr), _cell(c["x"] + rr) + 1):
                    if math.hypot(_centre(i) - c["x"], _centre(j) - c["z"]) <= rr:
                        self.blocked[j * N + i] = 1

    def free(self, x, z):
        return not self.blocked[_cell(z) * N + _cell(x)]

    def nearest_free(self, x, z):
        """The closest walkable point to (x, z), searching outward ring by ring."""
        ci, cj = _cell(x), _cell(z)
        if not self.blocked[cj * N + ci]:
            return x, z
        for ring in range(1, 40):
            best = None
            for j in range(cj - ring, cj + ring + 1):
                for i in (range(ci - ring, ci + ring + 1) if j in (cj - ring, cj + ring)
                          else (ci - ring, ci + ring)):
                    if 0 <= i < N and 0 <= j < N and not self.blocked[j * N + i]:
                        d = math.hypot(_centre(i) - x, _centre(j) - z)
                        if best is None or d < best[0]:
                            best = (d, _centre(i), _centre(j))
            if best:
                return best[1], best[2]
        return x, z

    def _segment(self, a, b):
        """(clear, weighted cost) of the straight segment a→b, sampled every quarter cell."""
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        steps = max(1, int(L / (CELL * 0.25)))
        total = 0.0
        for s in range(steps + 1):
            t = s / steps
            k = _cell(a[1] + (b[1] - a[1]) * t) * N + _cell(a[0] + (b[0] - a[0]) * t)
            if self.blocked[k]:
                return False, math.inf
            total += self.cost[k]
        return True, total / (steps + 1) * L

    def route(self, start, goal):
        """Walkable polyline [[x, z], ...] from start to goal (both snapped to free ground)."""
        sx, sz = self.nearest_free(*start)
        gx, gz = self.nearest_free(*goal)
        si, sj, gi, gj = _cell(sx), _cell(sz), _cell(gx), _cell(gz)
        if (si, sj) == (gi, gj):
            return [[sx, sz], [gx, gz]]
        s, g = sj * N + si, gj * N + gi
        D2 = math.sqrt(2)
        h = lambda k: CELL * (lambda dx, dz: (dx + dz) + (D2 - 2) * min(dx, dz))(
            abs(k % N - gi), abs(k // N - gj))
        dist = {s: 0.0}
        prev = {}
        heap = [(h(s), 0.0, s)]
        moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                 (1, 1, D2), (1, -1, D2), (-1, 1, D2), (-1, -1, D2)]
        found = False
        while heap:
            _, d, k = heapq.heappop(heap)
            if k == g:
                found = True
                break
            if d > dist.get(k, math.inf):
                continue
            i, j = k % N, k // N
            for di, dj, step in moves:
                ni, nj = i + di, j + dj
                if not (0 <= ni < N and 0 <= nj < N):
                    continue
                nk = nj * N + ni
                if self.blocked[nk]:
                    continue
                if di and dj and (self.blocked[j * N + ni] or self.blocked[nj * N + i]):
                    continue          # no squeezing diagonally past a corner
                nd = d + step * CELL * self.cost[nk]
                if nd < dist.get(nk, math.inf):
                    dist[nk] = nd
                    prev[nk] = k
                    heapq.heappush(heap, (nd + h(nk), nd, nk))
        if not found:
            return [[sx, sz], [sx, sz]]   # unreachable: stay put rather than phase through walls
        cells = [g]
        while cells[-1] != s:
            cells.append(prev[cells[-1]])
        cells.reverse()
        pts = [(sx, sz)] + [(_centre(k % N), _centre(k // N)) for k in cells[1:-1]] + [(gx, gz)]
        return [[round(x, 2), round(z, 2)] for x, z in self._smooth(pts)]

    def _smooth(self, pts):
        """Greedy string-pulling that never trades road for a cheaper-looking shortcut."""
        out = [pts[0]]
        i = 0
        while i < len(pts) - 1:
            j = i + 1
            walked = self._segment(pts[i], pts[j])[1]
            while j + 1 < len(pts):
                walked += self._segment(pts[j], pts[j + 1])[1]
                clear, cost = self._segment(pts[i], pts[j + 1])
                if not clear or cost > walked + 1e-6:
                    break
                j += 1
            out.append(pts[j])
            i = j
        return out


def path_length(path):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))


def point_along(path, distance):
    """((x, z), (fx, fz)) at `distance` along the polyline, clamped to its ends."""
    if len(path) < 2:
        return (path[0][0], path[0][1]), None
    for a, b in zip(path, path[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if distance <= seg and seg > 0:
            t = distance / seg
            return ((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                    ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg))
        distance -= seg
    a, b = path[-2], path[-1]
    seg = math.hypot(b[0] - a[0], b[1] - a[1])
    return (b[0], b[1]), (((b[0] - a[0]) / seg, (b[1] - a[1]) / seg) if seg else None)
