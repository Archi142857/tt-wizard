"""경사를 반영한 건물 사이 보행 시간 → data/travel_slope.csv (시간표 알고리즘 입력).

  python scripts/slope_travel.py                  # 마법 지도 거리표의 모든 지점 쌍(방향별) + 기숙사 동
  python scripts/slope_travel.py --window 20      # 경사를 재는 창 길이(m)를 바꿔 민감도 확인

입력
  data/magicmap/roads_graph_slope.json   graph_slopes.py 결과(노드 고도, 엣지 surface). 걸을 수 있는 엣지만 쓴다
  data/dem/                              지면 엣지의 단면을 2 m마다 읽는다. 없으면 노드 고도 사이를 직선으로 본다
  data/building_entrances.csv            지상 출입구 좌표(data/graph_patch/*.geojson 의 replace = true 출입구가 있으면 그것, 없는 기숙사 동은
                                         그 패치의 출입구). 그래도 없는 건물은 data/buildings_elevation.csv 의
  data/buildings_for_magicmap.csv        캠퍼스맵 좌표, 그것도 없으면 이 목록(GATE·71-1동 등)의 좌표
  data/magicmap/building_pair_times.csv  지점 목록과 마법 지도 평지 시간
  data/dorm_buildings.csv                기숙사 동(travel = Y). 마법 지도 표에는 919동뿐이라 나머지 동은 표 시간이 없다

방법
  경로      출입구는 그래프의 출입구 노드(graph_patch 출입구 접속선의 건물 쪽 끝)에서 출발한다. 접속선이 있는 출입구가
            하나도 없는 지점만 출입구(없으면 건물 좌표)에서 가장 가까운 길(그래프의 가장 큰 연결 요소)과 그보다 20 m 안쪽으로
            더 먼 길까지 직선으로 잇는다. 출발 건물의 모든 출입구에서 도착 건물의 모든 출입구까지 가장 짧은 경로를 찾는다
            (Dijkstra). 다른 건물의 출입구 노드는 지나가지 않는다(접속선은 그 건물을 드나들 때만 쓴다). 막은 엣지
            (graph_patch 의 type = block)는 쓰지 않는다. 오갈 때 같은 경로
  경사      경로를 따라 고도를 이어 붙이고(지면 구간은 DEM, 터널·다리는 양 끝 사이 직선, 출입구~길 접속 구간은 평지),
            2 m마다 앞뒤 15 m(창 30 m) 두 점의 높이차 ÷ 거리를 그 자리의 경사로 본다. DEM이 5 m 등고선으로 만든 것이라
            몇 m 구간의 경사는 오차에 휘둘리기 때문이다(1:1,000 표고점 검증 MAE 0.9 m)
  속도      Tobler 보행 함수 v(g) = v0 · exp(−3.5 |g + 0.05|) / exp(−3.5 × 0.05). 평지에서 v0, 완만한 내리막(−5 %)에서 가장 빠르다
  경사 계수  F = 경사 반영 시간 ÷ 평지 시간 (같은 경로, 방향별). v0와 무관하다
  결과      마법 지도 표 시간 × F. 평지 기준이 travel.csv(마법 지도)와 같아 두 파일의 차이는 경사 효과뿐이다.
            --base route 면 우리 경로의 경사 반영 시간(v0 = --speed)을 그대로 쓰고, travel.csv 의 표 쌍(source = magicmap)도
            우리 경로 평지 시간(source = route)으로 바꿔 두 파일의 평지 기준을 맞춘다(실측 행은 그대로).
            되돌리려면 --base magicmap(기본)으로 다시 돌린다(표 쌍의 route 행을 표 시간으로 되돌린다)
            표에 없는 쌍(기숙사 동)은 우리 경로 시간: 경사 반영은 travel_slope.csv, 평지(경로 길이 ÷ 1.1 m/s)는
            travel.csv 에 source = route 로 더한다(마법 지도 표 시간과 우리 경로 평지 시간은 중앙값 0.07분 차이)
            (출입구가 여러 곳인 건물을 거치면 더 빠른 쌍이 있어 삼각부등식이 성립하지 않는다. 탐색은 이를 감안해 하한을 잰다)

출력
  data/travel_slope.csv   from,to,minutes,source (= slope). python -m ttwizard search ... --travel data/travel_slope.csv
  data/route_stats.csv    쌍마다 마법 지도 시간, 우리 경로의 평지·경사 시간, 경사 계수, 최종 시간, 경로 길이, 오르막·내리막,
                          우리 경로와 마법 지도 표가 크게 다른 쌍 표시(check)
  data/travel.csv         표에 없는 쌍만 source = route 로 바꿔 쓴다(마법 지도·실측 행은 그대로)
  data/route_paths.json   웹 지도에 그릴 경로 모양. {"ids": [...], "paths": {"a|b": 인코딩한 선}} (a → b 방향,
                          Google polyline 형식·소수 5자리, 1 m 넘게 벗어나지 않는 점만 남김).
                          기숙사 동끼리는 그리지 않는다(수업이 없어 지도에 그 구간이 나올 일이 없고, 파일만 커진다)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import building_elevation as be  # noqa: E402
import graph_patch as gp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GRAPH = DATA / "magicmap" / "roads_graph_slope.json"
PAIRS = DATA / "magicmap" / "building_pair_times.csv"
ENTRANCES = DATA / "building_entrances.csv"
ELEVATION = DATA / "buildings_elevation.csv"
POINTS = DATA / "buildings_for_magicmap.csv"
OUT = DATA / "travel_slope.csv"
OUT_STATS = DATA / "route_stats.csv"
OUT_PATHS = DATA / "route_paths.json"
EXTRA = DATA / "dorm_buildings.csv"
FLAT = DATA / "travel.csv"
DOOR = 0.5  # 출입구 좌표가 그래프의 출입구 노드에서 이 안(m)이면 그 노드에서 출발
ALIASES = {"71-1": "71"}  # 제 출입구도 좌표도 없는 지점이 대신 쓸 건물(71-1동은 이제 출입구·좌표가 있어 쓰이지 않는다)
STAT_FIELDS = ["from", "to", "magicmap_min", "route_flat_min", "route_slope_min", "slope_factor", "minutes",
               "route_m", "ascent_m", "descent_m", "net_rise_m", "check"]


def tobler(grade, v0: float = 1.1):
    """경사(소수, 오르막 +)에 따른 보행 속도(m/s). 평지에서 v0."""
    g = np.clip(np.asarray(grade, float), -1.0, 1.0)
    return v0 * np.exp(-3.5 * np.abs(g + 0.05)) / math.exp(-3.5 * 0.05)


def _rows(path: Path) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def extra_ids(path: Path = EXTRA) -> list[str]:
    """마법 지도 표 밖에서 이동시간을 낼 지점(기숙사 동 목록의 travel = Y)."""
    return [r["building"].strip() for r in _rows(path) if (r.get("travel") or "").strip().upper() == "Y"]


def load_points(ids, entrances: Path = ENTRANCES, elevation: Path = ELEVATION,
                listing: Path = POINTS, extra: Path | None = None, patch=()) -> dict[str, list[tuple[float, float]]]:
    """지점 id → [(lon, lat)]: 그래프 패치의 제보 출입구(replace = true) → 지상 출입구 → 그래프 패치의 출입구 →
    캠퍼스맵 건물 좌표 → 목록 좌표 → 기숙사 동 목록 좌표 순으로 찾는다."""
    ents = defaultdict(list)
    for r in _rows(entrances):
        if r.get("lat") and r.get("lon"):
            ents[r["building"]].append((float(r["lon"]), float(r["lat"])))
    for b, pts in gp.patch_entrances(patch).items():
        if not ents.get(b):
            ents[b] = list(pts)
    for b, pts in gp.reported_entrances(patch).items():  # 제보·손으로 그린 출입구가 building_entrances.csv 보다 우선
        ents[b] = list(pts)
    coords = {}
    for path in (extra, listing, elevation):  # 뒤에 읽는 캠퍼스맵 좌표가 목록의 근사값보다 우선
        for r in _rows(path):
            if r.get("lat") and r.get("lon"):
                coords[r["building"]] = (float(r["lon"]), float(r["lat"]))
    out = {}
    for b in ids:
        for key in (b, ALIASES.get(b)):  # 제 출입구 → 제 좌표 → (둘 다 없으면) 대신 쓸 건물
            if key and ents.get(key):
                out[b] = ents[key]
                break
            if key and key in coords:
                out[b] = [coords[key]]
                break
    return out


def window_grades(s: np.ndarray, z: np.ndarray, window: float, step: float = 2.0):
    """경로 단면 (s, z) → 조각 길이 ds와 조각마다의 경사(앞뒤 window/2 두 점 사이 평균, 경로 끝에서는 잘린 창)."""
    L = float(s[-1]) if len(s) else 0.0
    if L <= 0:
        return np.zeros(0), np.zeros(0)
    n = max(1, math.ceil(L / step))
    edges = np.linspace(0.0, L, n + 1)
    mid = (edges[:-1] + edges[1:]) / 2
    h = window / 2
    lo, hi = np.clip(mid - h, 0, L), np.clip(mid + h, 0, L)
    g = (np.interp(hi, s, z) - np.interp(lo, s, z)) / np.maximum(hi - lo, 1e-9)
    return np.diff(edges), g


def simplify(xy: np.ndarray, tol: float = 1.0) -> np.ndarray:
    """Douglas–Peucker: 선에서 tol(m)보다 덜 벗어나는 점을 뺀다."""
    if len(xy) <= 2:
        return xy
    keep = np.zeros(len(xy), bool)
    keep[[0, -1]] = True
    stack = [(0, len(xy) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = xy[i], xy[j]
        ab = b - a
        L = float(np.hypot(*ab))
        pts = xy[i + 1:j]
        if L == 0:
            d = np.hypot(*(pts - a).T)
        else:
            d = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / L
        k = int(np.argmax(d))
        if d[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return xy[keep]


def encode_polyline(latlon) -> str:
    """Google polyline 인코딩(소수 5자리). latlon = [(lat, lon), ...]."""
    out, plat, plon = [], 0, 0
    for lat, lon in latlon:
        ilat, ilon = round(lat * 1e5), round(lon * 1e5)
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def decode_polyline(text: str) -> list[tuple[float, float]]:
    out, i, lat, lon = [], 0, 0, 0
    while i < len(text):
        vals = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(text[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            vals.append(~(result >> 1) if result & 1 else result >> 1)
        lat += vals[0]
        lon += vals[1]
        out.append((lat / 1e5, lon / 1e5))
    return out


class Router:
    """마법 지도 그래프 위 최단거리 경로와 경로 단면."""

    def __init__(self, graph: dict, proj: be.LocalProj, dem=None, step: float = 2.0,
                 slack: float = 20.0, cap: float = 150.0, through_doors: bool = False):
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial import cKDTree

        self.slack, self.cap, self.step = slack, cap, step
        self.through_doors = through_doors  # True: 다른 건물의 출입구 노드를 지나가도 된다(비교·검토용. 기본은 안 지나간다)
        nodes = graph["nodes"]
        self.ids = [n["id"] for n in nodes]
        index = {i: k for k, i in enumerate(self.ids)}
        self.n = len(nodes)
        lon = np.array([n["lng"] for n in nodes], float)
        lat = np.array([n["lat"] for n in nodes], float)
        self.P = np.column_stack(proj.fwd(lon, lat))
        self.z = np.array([np.nan if n.get("ele") is None else n["ele"] for n in nodes], float)
        self.proj = proj

        dist, surface, links = {}, {}, set()
        for e in graph["edges"]:
            if not e.get("walkable", True) or e.get("blocked"):  # blocked: graph_patch 의 type = block(실제로 없는 길)
                continue
            u, v = index[e["from"]], index[e["to"]]
            if u == v:
                continue
            k = (min(u, v), max(u, v))
            d = float(e["distance"])
            if k not in dist or d < dist[k]:
                dist[k] = d
            if e.get("role") == "entrance_link":
                links.add(k)
            surf = e.get("surface") or ("tunnel" if e.get("isTunnel") else "ground")
            if surface.get(k, "ground") == "ground":
                surface[k] = surf
        self.dist = dist
        keys = list(dist)
        a = np.array([k[0] for k in keys])
        b = np.array([k[1] for k in keys])
        d = np.array([dist[k] for k in keys])
        self.csr = csr_matrix((np.concatenate([d, d]), (np.concatenate([a, b]), np.concatenate([b, a]))),
                              shape=(self.n, self.n))
        _, lab = connected_components(self.csr, directed=False)
        main = Counter(lab[a]).most_common(1)[0][0]
        seg = np.array([k for k in keys if lab[k[0]] == main], int)
        # 직선 접속(출입구 노드가 없는 지점)의 대상: 출입구 접속선은 뺀다. 접속선은 그 건물을 드나드는 선이라, 다른 지점이
        # 거기에 붙으면 남의 출입구 노드에서 출발해 그 문을 지나가는 경로가 생긴다
        road = np.array([k for k in map(tuple, seg) if k not in links], int).reshape(-1, 2)
        self.S = road if len(road) else seg
        self.SA, self.SB = self.P[self.S[:, 0]], self.P[self.S[:, 1]]
        self.half = np.hypot(*(self.SB - self.SA).T) / 2
        self.stree = cKDTree((self.SA + self.SB) / 2)
        # 출입구 노드(graph_patch 의 출입구 접속선 건물 쪽 끝): 출입구가 이 노드 자리면 직선 접속 없이 이 노드에서 출발한다
        first = {}
        for u, v in map(tuple, seg):
            first.setdefault(int(u), (int(u), int(v)))
            first.setdefault(int(v), (int(u), int(v)))
        self.doors = {k: first[k] for k, n in enumerate(nodes) if n.get("entrance") and k in first}
        door_ids = list(self.doors)
        self.door_ids = door_ids
        self.dtree = cKDTree(self.P[door_ids]) if door_ids else None
        self.profiles = self._profiles(keys, surface, dem)

    def _profiles(self, keys, surface, dem) -> dict[tuple[int, int], tuple[np.ndarray, np.ndarray]]:
        """엣지 (작은 id, 큰 id) → (s, z). 지면이고 DEM이 있으면 step마다 DEM, 아니면 양 끝 노드 사이 직선."""
        out = {}
        sampled = [k for k in keys if dem is not None and surface.get(k) == "ground"]
        for k in keys:
            out[k] = (np.array([0.0, self.dist[k]]), np.array([self.z[k[0]], self.z[k[1]]]))
        if not sampled:
            return out
        xs, ys, ts, spans = [], [], [], []
        for u, v in sampled:
            L = float(np.hypot(*(self.P[v] - self.P[u])))
            t = np.linspace(0, 1, max(1, math.ceil(L / self.step)) + 1)
            xs.append(self.P[u, 0] + (self.P[v, 0] - self.P[u, 0]) * t)
            ys.append(self.P[u, 1] + (self.P[v, 1] - self.P[u, 1]) * t)
            ts.append(t)
            spans.append(len(t))
        lon, lat = self.proj.inv(np.concatenate(xs), np.concatenate(ys))
        Z = np.asarray(dem.sample(lon, lat), float)
        pos = 0
        for (u, v), t, m in zip(sampled, ts, spans):
            z = Z[pos:pos + m].copy()
            pos += m
            z[0], z[-1] = self.z[u], self.z[v]  # 노드 고도(graph_slopes 와 같은 값)에 맞춘다
            out[(u, v)] = (t * self.dist[(u, v)], z)
        return out

    def attach(self, lon: float, lat: float) -> dict[int, tuple]:
        """출입구 → {노드: (거리, 출입구~접점 직선거리, 엣지, 엣지 위 접점 위치 s, 출입구 좌표(m))}."""
        q = np.array(self.proj.fwd(lon, lat), float).ravel()
        if self.dtree is not None:  # 출입구 노드 자리: 그 노드에서 바로 출발(벽 너머 길로 직선을 긋지 않는다)
            near = self.dtree.query_ball_point(q, r=DOOR)
            if near:
                out = {}
                for j in near:
                    node = self.door_ids[int(j)]
                    k = self.doors[node]
                    out[node] = (0.0, 0.0, k, 0.0 if node == k[0] else self.dist[k], (float(q[0]), float(q[1])))
                return out
        cand = np.array(self.stree.query_ball_point(q, r=self.cap + self.half.max()), int)
        if not len(cand):
            return {}
        A, B = self.SA[cand], self.SB[cand]
        ab = B - A
        L2 = np.einsum("ij,ij->i", ab, ab)
        t = np.clip(np.einsum("ij,ij->i", q - A, ab) / np.where(L2 == 0, 1, L2), 0, 1)
        gap = np.hypot(*(q - (A + ab * t[:, None])).T)
        ok = gap <= min(gap.min() + self.slack, self.cap)
        out = {}
        for j, tj, dj in zip(cand[ok], t[ok], gap[ok]):
            k = (int(self.S[j, 0]), int(self.S[j, 1]))
            L = self.dist[k]
            for node, along in ((k[0], tj * L), (k[1], (1 - tj) * L)):
                total = float(dj + along)
                if total < out.get(node, (math.inf,))[0]:
                    out[node] = (total, float(dj), k, float(tj * L), (float(q[0]), float(q[1])))
        return out

    def is_door(self, lon: float, lat: float) -> bool:
        """출입구 좌표가 그래프 출입구 노드(접속선의 출입구 쪽 끝) 자리인가."""
        if self.dtree is None:
            return False
        q = np.array(self.proj.fwd(lon, lat), float).ravel()
        return bool(self.dtree.query_ball_point(q, r=DOOR))

    def _edge_piece(self, k, s_from: float, s_to: float):
        """엣지 k 단면에서 s_from → s_to 부분 (거꾸로도 된다). 반환 (길이 누적 s, z)."""
        s, z = self.profiles[k]
        lo, hi = min(s_from, s_to), max(s_from, s_to)
        inner = (s > lo) & (s < hi)
        ss = np.concatenate([[lo], s[inner], [hi]])
        zz = np.interp(ss, s, z)
        if s_from > s_to:
            ss, zz = ss[::-1], zz[::-1]
        return np.abs(ss - s_from), zz

    def profile(self, start, nodes: list[int], end):
        """출입구 → 접점 → 노드들 → 접점 → 출입구 단면 (s, z). start/end = attach() 값."""
        parts_s, parts_z = [], []
        offset = 0.0

        def add(s, z):
            nonlocal offset
            parts_s.append(s + offset)
            parts_z.append(z)
            offset += float(s[-1])

        _, dj, k, sq, _ = start
        z_q = float(np.interp(sq, *self.profiles[k]))
        add(np.array([0.0, dj]), np.array([z_q, z_q]))  # 출입구~길은 평지로 본다
        add(*self._edge_piece(k, sq, 0.0 if nodes[0] == k[0] else self.dist[k]))
        for u, v in zip(nodes[:-1], nodes[1:]):
            k2 = (min(u, v), max(u, v))
            add(*self._edge_piece(k2, 0.0 if u == k2[0] else self.dist[k2], self.dist[k2] if u == k2[0] else 0.0))
        _, dj, k, sq, _ = end
        add(*self._edge_piece(k, 0.0 if nodes[-1] == k[0] else self.dist[k], sq))
        z_q = float(np.interp(sq, *self.profiles[k]))
        add(np.array([0.0, dj]), np.array([z_q, z_q]))
        s, z = np.concatenate(parts_s), np.concatenate(parts_z)
        keep = np.concatenate([[True], np.diff(s) > 1e-6])  # 같은 자리 점은 하나만
        s, z = s[keep], z[keep]
        known = ~np.isnan(z)
        if not known.any():
            z = np.zeros_like(s)  # DEM 밖 경로: 평지로
        elif not known.all():
            z = np.interp(s, s[known], z[known])  # 모르는 구간은 앞뒤 값 사이 직선
        return s, z

    def geometry(self, start, nodes: list[int], end) -> np.ndarray:
        """출입구 → 접점 → 노드들 → 접점 → 출입구 좌표(m)."""
        def on_edge(rec):
            _, _, k, sq, q = rec
            t = sq / self.dist[k] if self.dist[k] > 0 else 0.0
            return q, self.P[k[0]] + (self.P[k[1]] - self.P[k[0]]) * t

        q0, a0 = on_edge(start)
        q1, a1 = on_edge(end)
        return np.vstack([q0, a0, self.P[nodes], a1, q1])

    def access(self, pts) -> tuple[dict[int, tuple], bool]:
        """출입구 좌표들 → ({접근 노드: attach 기록}, 직선 접속을 썼는가).
        접속선이 있는 출입구(그래프의 출입구 노드)만 쓴다(접속선이 없는 출입구는 직선이 벽을 뚫을 수 있다).
        그런 출입구가 하나도 없는 지점만 가장 가까운 길까지 직선으로 잇는다."""
        doors = [p for p in pts if self.is_door(*p)]
        best = {}
        for lon, lat in (doors or pts):
            for node, rec in self.attach(lon, lat).items():
                if rec[0] < best.get(node, (math.inf,))[0]:
                    best[node] = rec
        return best, not doors

    def _core(self):
        """출입구 노드로 '들어가는' 방향의 엣지를 뺀 그래프(경로 찾기용. 한 번 만들어 둔다)."""
        if getattr(self, "_core_csr", None) is None:
            from scipy.sparse import csr_matrix

            door = np.zeros(self.n, bool)
            door[self.door_ids] = True
            coo = self.csr.tocoo()
            keep = np.ones(len(coo.col), bool) if self.through_doors else ~door[coo.col]
            self._door = door
            self._core_csr = csr_matrix((coo.data[keep], (coo.row[keep], coo.col[keep])), shape=(self.n, self.n))
        return self._core_csr

    def search(self, sources: list[dict[int, tuple]]):
        """출발 지점마다(접근 노드 {노드: attach 기록}) Dijkstra → (거리[지점, 노드], 앞 노드[지점, 노드]).

        다른 건물의 출입구 노드는 지나가지 않는다: 출입구 접속선은 그 건물을 드나들 때만 쓴다. 한 출입구에서 나가는 접속선
        둘을 이어 길과 길 사이를 가로지르는 지름길로 쓰면(접속선은 건물·담장만 피해 그은 선이라 화단·단차를 넘을 수 있다)
        없는 길이 생긴다. 그래서 출입구 노드로 들어가는 방향을 뺀 그래프에서 찾고, 도착은 arrive() 가 맡는다."""
        from scipy.sparse import bmat, csr_matrix
        from scipy.sparse.csgraph import dijkstra

        m = len(sources)
        rows, cols, vals = [], [], []
        for i, acc in enumerate(sources):
            for node, rec in acc.items():
                rows.append(i)
                cols.append(node)
                vals.append(max(rec[0], 1e-6))
        link = csr_matrix((vals, (rows, cols)), shape=(m, self.n))
        M = bmat([[self._core(), None], [link, csr_matrix((m, m))]], format="csr")
        return dijkstra(M, directed=True, indices=list(range(self.n, self.n + m)), return_predecessors=True)

    def arrive(self, dist: np.ndarray, pred: np.ndarray, target: dict[int, tuple]):
        """search() 의 한 줄(출발 지점 하나의 dist, pred)에서 도착 지점의 접근 노드까지 → (길이 m, 노드 줄) 또는 None.
        도착 지점의 출입구 노드에는 그 출입구에서 나가는 접속선의 첫 꼭짓점까지 온 거리 + 그 엣지 길이로 닿는다."""
        self._core()
        best = None
        for n, rec in target.items():
            t = dist[n] + rec[0]  # 길 위 접점(직선 접속), 또는 출발 지점과 같이 쓰는 출입구 노드
            if np.isfinite(t) and (best is None or t < best[0]):
                best = (float(t), int(n), None)
            if self._door[n]:
                lo, hi = self.csr.indptr[n], self.csr.indptr[n + 1]
                for u, w in zip(self.csr.indices[lo:hi], self.csr.data[lo:hi]):
                    t = dist[u] + w
                    if np.isfinite(t) and (best is None or t < best[0]):
                        best = (float(t), int(u), int(n))
        if best is None:
            return None
        total, last, door = best
        path = [last]
        while 0 <= pred[path[-1]] < self.n:  # 가상 출발점(n 이상)에 닿으면 멈춘다
            path.append(int(pred[path[-1]]))
        path.reverse()
        if door is not None:
            path.append(door)
        return total, path

    def paths(self, points: dict[str, list[tuple[float, float]]]):
        """모든 지점 쌍(순서 없는)의 최단거리 경로 → {(a, b): (출발 기록, 노드 줄, 도착 기록, 길이 m)} (a → b 방향)."""
        ids = [b for b in points if points[b]]
        acc = {}
        self.fallback = []  # 출입구 노드(접속선)가 하나도 없어 가장 가까운 길까지 직선으로 이은 지점
        for b in ids:
            acc[b], straight = self.access(points[b])
            if straight:
                self.fallback.append(b)
        ids = [b for b in ids if acc[b]]
        dist, pred = self.search([acc[b] for b in ids])
        out = {}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                got = self.arrive(dist[i], pred[i], acc[b])
                if got is None:
                    continue
                total, path = got
                out[(a, b)] = (acc[a][path[0]], path, acc[b][path[-1]], total)
        return out

    def routes(self, points: dict[str, list[tuple[float, float]]]):
        """모든 지점 쌍(순서 없는)의 최단거리 경로 → {(a, b): (s, z, 좌표)} (a → b 방향)."""
        return {k: (*self.profile(start, path, stop), self.geometry(start, path, stop))
                for k, (start, path, stop, _) in self.paths(points).items()}


def write_flat(path: Path, route_flat: dict[tuple[str, str], float], replace=("route",),
               table: dict[tuple[str, str], float] | None = None) -> int:
    """travel.csv 에 우리 경로의 평지 시간(source = route)을 쓴다. replace 에 든 출처의 행만 바꾸고(기본: 옛 route 행),
    다른 출처(마법 지도·실측 등) 행은 그대로 둔다. --base route 일 때는 replace = (route, magicmap).
    이번에 안 나온 옛 route 행은 지운다. 다만 table(마법 지도 표 시간, 분)에 있는 쌍이면 표 값(source = magicmap)으로 되돌린다
    (--base route 로 돌렸다가 magicmap 기준으로 다시 돌릴 때 표 쌍이 빠지지 않게). 표 값으로 되돌린 행 수를 돌려준다."""
    rows, restored = {}, 0
    for r in _rows(path):
        k = (r["from"].strip(), r["to"].strip())
        src = (r.get("source") or "").strip()
        if src != "route" or k in route_flat:
            rows[k] = (r["minutes"], src)
        elif table and k in table:
            rows[k] = (f"{table[k]:.2f}", "magicmap")
            restored += 1
    for k, m in route_flat.items():
        if rows.get(k, ("", "route"))[1] in replace:
            rows[k] = (f"{m:.2f}", "route")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:  # travel.py 가 BOM 없는 UTF-8로 읽는다
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["from", "to", "minutes", "source"])
        for (a, b), (m, src) in sorted(rows.items()):
            w.writerow([a, b, m, src])
    return restored


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default=str(GRAPH))
    ap.add_argument("--pairs", default=str(PAIRS))
    ap.add_argument("--dem", nargs="+", default=[str(DATA / "dem")])
    ap.add_argument("--max-res", type=float, default=5.0, help="이보다 거친 DEM(m)은 쓰지 않는다")
    ap.add_argument("--entrances", default=str(ENTRANCES))
    ap.add_argument("--elevation", default=str(ELEVATION))
    ap.add_argument("--points", default=str(POINTS))
    ap.add_argument("--extra", default=str(EXTRA), help="표 밖 지점(기숙사 동, travel = Y). 빈 값이면 표 지점만")
    ap.add_argument("--patch", nargs="*", default=[str(gp.PATCH_DIR)], help="출입구를 더 읽을 그래프 패치(graph_patch.py)")
    ap.add_argument("--flat", default=str(FLAT), help="표 밖 쌍의 평지 시간을 source = route 로 더할 travel.csv. 빈 값이면 안 쓴다")
    ap.add_argument("--window", type=float, default=30.0, help="경사를 재는 창 길이(m)")
    ap.add_argument("--speed", type=float, default=1.1, help="평지 보행 속도(m/s). --base route 일 때 쓴다")
    ap.add_argument("--slack", type=float, default=20.0, help="가장 가까운 길보다 이만큼 먼 길까지 접속 후보(m)")
    ap.add_argument("--base", choices=["magicmap", "route"], default="magicmap",
                    help="magicmap: 마법 지도 시간 × 경사 계수, route: 우리 경로의 경사 반영 시간")
    ap.add_argument("-o", "--output", default=str(OUT))
    ap.add_argument("--stats", default=str(OUT_STATS))
    ap.add_argument("--paths", default=str(OUT_PATHS), help="웹 지도용 경로 모양(JSON)")
    args = ap.parse_args(argv)

    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    magic = {}
    for r in _rows(Path(args.pairs)):
        if r["from"] != r["to"]:
            magic[(r["from"], r["to"])] = float(r["time_s"]) / 60
    base_ids = {a for a, _ in magic} | {b for _, b in magic}
    extra = [b for b in (extra_ids(Path(args.extra)) if args.extra else []) if b not in base_ids]
    ids = sorted(base_ids | set(extra), key=be.building_key)
    points = load_points(ids, Path(args.entrances), Path(args.elevation), Path(args.points),
                         Path(args.extra) if args.extra else None, args.patch or [])
    missing = [b for b in ids if b not in points]

    dem = None
    paths = [p for p in be.dem_paths(args.dem) if p.exists()] if args.dem else []
    if paths:
        lon = [n["lng"] for n in graph["nodes"]]
        lat = [n["lat"] for n in graph["nodes"]]
        dem = be.Dem(paths, bbox=(min(lat) - 0.001, min(lon) - 0.001, max(lat) + 0.001, max(lon) + 0.001))
        dem.layers = [L for L in dem.layers if abs(L.res[0]) <= args.max_res]
        dem = dem if dem.layers else None
    print(f"그래프: 노드 {len(graph['nodes']):,}개 · 엣지 {len(graph['edges']):,}개 · 지점 {len(ids)}개"
          + (f"(표 밖 기숙사 동 {len(extra)}개)" if extra else "")
          + f" (출입구 여러 곳 {sum(1 for b in ids if len(points.get(b, [])) > 1)}개)"
          + (f" · 위치 없음 {missing}" if missing else ""))
    print("단면: " + (", ".join(f"{L.name} ({L.res[0]:g} m)" for L in dem.layers) + " + 노드 고도" if dem
                     else "DEM 없음 → 노드 고도 사이 직선") + f" · 경사 창 {args.window:g} m")

    router = Router(graph, be.LocalProj(), dem=dem)
    profiles = router.routes(points)
    if router.fallback:
        print(f"출입구 접속선이 없어 가장 가까운 길까지 직선으로 이은 지점 {len(router.fallback)}개: {', '.join(router.fallback)}")
    rows, minutes, route_flat = [], {}, {}
    for (a, b), (s, z, _) in profiles.items():
        ds, g = window_grades(s, z, args.window)
        L = float(s[-1])
        flat = L / args.speed
        for x, y, sign in ((a, b, 1.0), (b, a, -1.0)):
            gg = sign * g
            t = float(np.sum(ds / tobler(gg, args.speed))) if L > 0 else 0.0
            f = t / flat if flat > 1.0 else 1.0
            m = magic.get((x, y))
            final = m * f if (args.base == "magicmap" and m is not None) else t / 60
            minutes[(x, y)] = final
            if m is None or args.base == "route":
                route_flat[(x, y)] = flat / 60
            rel = abs(flat / 60 - m) if m is not None else 0.0
            rows.append({"from": x, "to": y, "magicmap_min": "" if m is None else f"{m:.2f}",
                         "route_flat_min": f"{flat / 60:.2f}", "route_slope_min": f"{t / 60:.2f}",
                         "slope_factor": f"{f:.3f}", "minutes": f"{final:.2f}",
                         "route_m": f"{L:.0f}", "ascent_m": f"{np.sum(np.clip(gg, 0, None) * ds):.1f}",
                         "descent_m": f"{np.sum(np.clip(-gg, 0, None) * ds):.1f}",
                         "net_rise_m": f"{sign * (z[-1] - z[0]):+.1f}",
                         "check": "경로 다름" if m is not None and rel > 1.0 and rel > 0.3 * m else ""})
    rows.sort(key=lambda r: (be.building_key(r["from"]), be.building_key(r["to"])))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:  # travel.py 가 BOM 없는 UTF-8로 읽는다
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["from", "to", "minutes", "source"])
        for r in rows:
            w.writerow([r["from"], r["to"], r["minutes"], "slope"])
    with open(args.stats, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=STAT_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    restored = 0
    if args.flat and (route_flat or Path(args.flat).exists()):
        restored = write_flat(Path(args.flat), route_flat, ("route", "magicmap") if args.base == "route" else ("route",),
                              table=None if args.base == "route" else magic)
    proj = router.proj
    paths = {}
    skip = set(extra)
    for (a, b), (_, _, xy) in profiles.items():
        if a in skip and b in skip:  # 기숙사 동끼리: 지도에 나올 일이 없다
            continue
        xy = simplify(xy, 1.0)
        lon, lat = proj.inv(xy[:, 0], xy[:, 1])
        paths[f"{a}|{b}"] = encode_polyline(zip(np.atleast_1d(lat), np.atleast_1d(lon)))
    Path(args.paths).write_text(json.dumps({"ids": [b for b in ids if b in points], "paths": paths}, ensure_ascii=False,
                                           separators=(",", ":")), encoding="utf-8")

    F = np.array([float(r["slope_factor"]) for r in rows])
    gap = np.array([float(r["route_flat_min"]) - float(r["magicmap_min"]) for r in rows if r["magicmap_min"]])
    print(f"\n저장: {out} ({len(rows):,}쌍, 기준 {'마법 지도 시간 × 경사 계수' if args.base == 'magicmap' else '우리 경로'}"
          + (f", 표 밖 {sum(1 for k in route_flat if k not in magic):,}쌍은 우리 경로" if args.base == "magicmap" and route_flat else "") + ")")
    if args.flat and (route_flat or restored):
        print(f"      {args.flat} ({'모든' if args.base == 'route' else '표 밖'} {len(route_flat):,}쌍 평지 시간, source = route"
              + (f"; 표 쌍 {restored:,}개는 표 시간으로 되돌림" if restored else "") + ")")
    print(f"      {args.stats}\n      {args.paths} (경로 {len(paths):,}개)")
    if len(gap):
        print(f"  우리 경로(평지) − 마법 지도 표: 중앙값 {np.median(gap):+.2f}분, |차이| 90% {np.percentile(np.abs(gap), 90):.2f}분,"
              f" 크게 다른 쌍(1분·30% 넘게) {sum(1 for r in rows if r['check'])}개")
    both = np.array([float(r["route_slope_min"]) - float(r["magicmap_min"]) * float(r["slope_factor"]) for r in rows if r["magicmap_min"]])
    if len(both):
        print(f"  기준에 따른 차이(우리 경로 경사 시간 − 표 × 경사 계수): 1분 넘게 다른 쌍 {int(np.sum(np.abs(both) > 1)):,}개"
              f"(우리 쪽이 긴 것 {int(np.sum(both > 1)):,} · 짧은 것 {int(np.sum(both < -1)):,}), 2분 넘게 {int(np.sum(np.abs(both) > 2)):,}개,"
              f" 범위 {both.min():+.1f} ~ {both.max():+.1f}분")
    print(f"  경사 계수: 중앙값 {np.median(F):.3f}, 10% {np.percentile(F, 10):.3f}, 90% {np.percentile(F, 90):.3f},"
          f" 최대 {F.max():.2f}, 평지보다 빠른 방향 {np.mean(F < 1) * 100:.0f}%")
    diff = sorted(((minutes[(r['from'], r['to'])] - float(r["magicmap_min"] or 0), r) for r in rows if r["magicmap_min"]),
                  key=lambda x: -x[0])[:5]
    print("  경사로 가장 많이 늘어난 쌍: " + ", ".join(
        f"{r['from']}→{r['to']} {r['magicmap_min']}→{r['minutes']}분(오르막 {r['ascent_m']} m)" for _, r in diff))
    pairs = sorted(((abs(minutes[(a, b)] - minutes[(b, a)]), a, b) for (a, b) in profiles), reverse=True)[:3]
    print("  방향에 따라 가장 다른 쌍: " + ", ".join(
        f"{a}→{b} {minutes[(a, b)]:.1f}분 / {b}→{a} {minutes[(b, a)]:.1f}분" for _, a, b in pairs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
