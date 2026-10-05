"""출입구 접속선: 출입구에서 길까지 건물·담장·옹벽을 피해 걷는 가장 짧은 선 → data/graph_patch/links.geojson

  python scripts/entrance_links.py              # 다시 만들면 links.geojson 을 덮어쓴다
  python scripts/entrance_links.py --report     # 확인이 필요한 접속선(길다·가파르다·출입구가 윤곽 깊이 안쪽) 목록도

경로 계산(slope_travel.py)은 출입구가 그래프의 출입구 노드면 그 노드에서 출발한다. 이 스크립트는 모든 출입구에 그 노드와
접속선을 만들어, 출입구에서 가장 가까운 길까지 직선을 긋던 방식(건물·벽을 뚫고 지나가는 선이 생겼다)을 대신한다.

입력
  data/magicmap/roads_graph_updated.json + data/graph_patch/*.geojson(이 파일 빼고)의 길   접속 대상(걸을 수 있는 엣지,
                                         가장 큰 연결 요소. 다른 출입구의 접속선·막은 엣지·터널은 빼고)
  data/building_entrances.csv           출입구(층 추정·OSM 출처). 패치에 replace = true 출입구(손으로 확인한 것)가 있는 동은 그것만 쓰고,
                                         csv 에 없는 기숙사 동은 패치의 자동 출입구(dorm.geojson). 손으로 그린 접속선이 이미 있는
                                         출입구는 건너뛴다
  data/dorm_buildings.csv               travel = N 인 동(919: 919A~D 네 동이 대신한다)은 출입구를 쓰지 않는다
  data/topo/*/N1A_B0010000              1:1,000 수치지형도 건물. 무벽건물(캐노피·자전거보관대·버스 쉼터)은 지나갈 수 있다
  data/topo/*/N1L_B0020000 등           장애물 선(BARRIERS): 담장·철책·판자담(문주 제외), 옹벽·석축, 절토, 가드펜스, 제방, 벼랑바위
  data/topo/*/N1A_C0390000              계단(면). 접속선이 지나가면 kind = steps
                                         (수치지형도 원본은 저장소에 없다. 국토정보플랫폼에서 받아 PC 에 둔다: docs/topo.md)
  data/dem/                             접속선 경사(확인 표시용)

방법
  0.5 m 격자에 건물과 장애물 선(폭 0.9 m)을 칠하고, 출입구 칸에서 8방향 Dijkstra로 가장 가까운 길 칸까지 간다(길에 닿으면 그
  너머로는 퍼지지 않는다). 출입구가 건물 윤곽 안쪽이면(1:1,000 윤곽은 지붕선이라 처마·캐노피 밑 출입구가 안쪽에 찍힌다)
  그 깊이 + 1 m 안의 건물 칸은 지나갈 수 있게 한다. 가장 가까운 길보다 SLACK m 안쪽으로 더 먼 다른 길(접점끼리 SPACING m 넘게
  떨어진 것)까지 한 출입구에 최대 MAX_LINKS 개. 격자 경로는 줄 당기기로 꺾인 선(장애물을 피하는 꼭짓점만)으로 줄인다.
  패치의 replace 출입구는 properties 로 조건을 바꿀 수 있다: max_links(접속선 수), slack(m), clear(m: 필로티 밑처럼 윤곽 깊이 안쪽에
  있는 문에서 건물 칸을 지나갈 수 있는 반경). 패치의 type = barrier 선·면은 수치지형도에 없는 장애물로 같이 칠한다.
  같은 자리 출입구(140·140-1·140-2동처럼 번호가 여럿인 건물)는 하나로 만든다.

출력 (data/graph_patch/links.geojson)
  type = path, role = entrance_link: 첫 점 = 출입구(그래프 출입구 노드), 끝 점 = 길 위 접점. building(첫 동), entrances
  ('동#번호' 목록), kind(footway, 계단을 지나면 steps), costFactor, snap 0.5·link 1.0(끝을 정확히 그 접점에 붙인다),
  length_m(접속선 길이), straight_m(접점까지 직선거리), detour(꺾여 돌아가면 true), max_grade(DEM, 6 m 창 %),
  door_depth_m(출입구가 건물 윤곽 안쪽으로 들어간 깊이), door_clear_m(그 출입구에 준 clear),
  check(확인 필요: 'long' 25 m 넘음, 'steep' DEM 경사 30 % 넘고 높이차 2 m 넘음, 'deep' 출입구가 윤곽 안 3 m 넘게)
  접속선을 못 찾은 출입구(MAX_DIST m 안에 길이 없거나 막힘)는 type = entrance_unlinked 점으로 남긴다(손으로 그려야 한다)
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import building_elevation as be  # noqa: E402
import graph_patch as gp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TOPO = DATA / "topo"
OUT = gp.PATCH_DIR / "links.geojson"

CELL = 0.5        # 격자(m)
MAX_DIST = 80.0   # 출입구에서 이 경로 거리 안의 길만
SLACK = 20.0      # 가장 가까운 길보다 이만큼 더 먼 길까지 접속선 후보
SPACING = 8.0     # 접점끼리 이만큼 떨어져야 따로 잇는다
MAX_LINKS = 4
USEFUL = 5.0      # 다른 길로 가는 접속선은 이미 고른 접속선 + 길보다 이만큼 넘게 짧을 때만
NET_LIMIT = 400.0
WALL_HALF = 0.45  # 장애물 선 반폭(m)
DOOR_CLEAR = 0.7  # 출입구 둘레 이 안의 장애물 칸은 지나갈 수 있다(출입구가 벽 선 바로 위에 찍힌 경우)
LONG, STEEP, DEEP = 25.0, 0.30, 3.0
BUILDING = "B0010000"
STAIRS = "C0390000"
# 1:1,000 수치지형도 장애물 선: 레이어 → 지나갈 수 없는 것 고르기
BARRIERS = {
    "B0020000": lambda a: a.get("구분") != "문주",   # 담장·철책·판자담. 문주(문기둥)는 문 자리
    "F0040000": lambda a: True,                       # 옹벽·석축(상단·하단)
    "F0030000": lambda a: True,                       # 절토
    "C0530000": lambda a: True,                       # 가드펜스
    "C0050000": lambda a: True,                       # 제방
    "G0030000": lambda a: a.get("용도") == "벼랑바위",
}
LINK_SOURCE = "자동 접속선(scripts/entrance_links.py, 수치지형도 1:1,000 건물·장애물 회피)"
SOURCE = ("출입구 접속선: 국토지리정보원 1:1,000 수치지형도(2025) 건물·담장·옹벽 등을 피해 출입구에서 가장 가까운 길까지 "
          "걷는 가장 짧은 선(tt-wizard scripts/entrance_links.py)")


# ---------------------------------------------------------------- 읽기

def sheet_dirs(topo: Path = TOPO) -> list[Path]:
    """1:1,000 도엽 폴더(도엽번호 9자리)."""
    import re

    pat = re.compile(r"_(\d{9})_")
    return sorted(p for p in topo.iterdir() if p.is_dir() and pat.search(p.name)) if topo.exists() else []


def read_layer(dirs, layer: str, proj: be.LocalProj):
    """도엽들의 N1?_<layer>.shp → [(shapely 도형(로컬 m), 속성)]. EPSG:5186 → 경위도 → 로컬 m."""
    import shapefile
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform

    tr = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)

    def to_m(x, y, z=None):
        lon, lat = tr.transform(np.asarray(x), np.asarray(y))
        return proj.fwd(lon, lat)

    out = []
    for d in dirs:
        for p in sorted(d.glob(f"N1?_{layer}.shp")):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = shapefile.Reader(str(p), encoding="cp949", encodingErrors="replace")
                names = [f[0] for f in r.fields[1:]]
                for sr in r.iterShapeRecords():
                    if not sr.shape.points:
                        continue
                    g = transform(to_m, shape(sr.shape.__geo_interface__))
                    if not g.is_valid:
                        g = g.buffer(0)
                    out.append((g, dict(zip(names, sr.record))))
    return out


def base_graph(graph_path: Path, patch_files) -> dict:
    """받은 그래프 + 패치의 길(links.geojson 제외). 접속 대상."""
    graph = json.loads(Path(graph_path).read_text(encoding="utf-8-sig"))
    gp.apply_patch(graph, gp.read_patches(patch_files))  # 패치가 없어도 끊긴 갈림목은 잇는다
    return graph


def entrance_list(entrances: Path, patch_files, skip=()) -> tuple[list[dict], dict]:
    """접속선을 만들 출입구 [{building, no, lon, lat}] (같은 자리는 하나로 합치기 전), 건너뛴 출입구 정보.
    skip: 출입구를 쓰지 않는 동(기숙사 동 목록의 travel = N. 919 는 919A~D 가 대신한다).

    동마다 출입구는 slope_travel.load_points 와 같은 차례로 고른다: 패치의 replace = true 출입구(손으로 확인한 것. 번호 = no, 없으면 r1, r2 …)가
    있으면 그것만, 없으면 building_entrances.csv, 그것도 없으면 패치의 자동 출입구(기숙사 동. 번호 p1, p2 …).
    손으로 그린 접속선(패치의 role = entrance_link)이 이미 나가는 출입구(0.5 m 안)는 건너뛴다."""
    feats = gp.read_patches(patch_files)
    reported = gp.reported_entrances(patch_files)
    curated = []  # 손으로 그린 접속선의 출입구 쪽 끝
    for f in feats:
        p, g = f.get("properties") or {}, f.get("geometry") or {}
        if p.get("role") == "entrance_link" and g.get("type") == "LineString":
            curated.append(tuple(map(float, g["coordinates"][0][:2])))
    skip = set(skip)
    rows = [r for r in gp._rows(entrances) if r.get("lat") and r.get("lon") and r["building"] not in skip]
    have_csv = {r["building"] for r in rows}
    out, skipped = [], {"reported": sorted(reported), "curated": []}
    opts = {}  # replace 출입구 (동, lon, lat) → 번호(no)와 접속선 조건(max_links·slack·clear)
    for f in feats:
        p, g = f.get("properties") or {}, f.get("geometry") or {}
        if p.get("type") == "entrance" and p.get("replace") and g.get("type") == "Point" and p.get("building"):
            o = {k: p[k] for k in ("no", "max_links", "slack", "clear") if p.get(k) not in (None, "")}
            if o:
                opts[(str(p["building"]), *map(float, g["coordinates"][:2]))] = o
    for b, pts in reported.items():
        if b in skip:
            continue
        for i, (lon, lat) in enumerate(pts):
            o = opts.get((b, float(lon), float(lat)), {})
            out.append({"building": b, "lon": float(lon), "lat": float(lat), **o, "no": str(o.get("no") or f"r{i + 1}")})
    for r in rows:
        b = r["building"]
        if b in reported:
            continue
        out.append({"building": b, "no": str(r.get("entrance_no") or ""), "lon": float(r["lon"]), "lat": float(r["lat"])})
    k = defaultdict(int)
    for b, pts in gp.patch_entrances(patch_files).items():  # 패치의 자동 출입구(기숙사 동): csv 에 없는 동만
        if b in reported or b in have_csv or b in skip:
            continue
        for lon, lat in pts:
            k[b] += 1
            out.append({"building": b, "no": f"p{k[b]}", "lon": float(lon), "lat": float(lat)})
    keep = []
    proj = be.LocalProj()
    cxy = [np.ravel(proj.fwd(lon, lat)) for lon, lat in curated]
    for e in out:
        q = np.ravel(proj.fwd(e["lon"], e["lat"]))
        if any(np.hypot(*(q - c)) <= 0.5 for c in cxy):
            skipped["curated"].append(f"{e['building']}#{e['no']}")
            continue
        keep.append(e)
    return keep, skipped


# ---------------------------------------------------------------- 격자

class Grid:
    def __init__(self, box, cell: float = CELL):
        x0, y0, x1, y1 = box
        self.x0, self.y1, self.cell = x0, y1, cell
        self.nx, self.ny = int(math.ceil((x1 - x0) / cell)), int(math.ceil((y1 - y0) / cell))
        from rasterio.transform import from_origin
        self.tf = from_origin(x0, y1, cell, cell)

    def rc(self, x, y):
        return int((self.y1 - y) / self.cell), int((x - self.x0) / self.cell)

    def xy(self, r, c):
        return self.x0 + (c + 0.5) * self.cell, self.y1 - (r + 0.5) * self.cell

    def burn(self, shapes, dtype="uint8", all_touched=False):
        from rasterio.features import rasterize

        out = np.zeros((self.ny, self.nx), dtype=dtype)
        shapes = list(shapes)
        for s in range(0, len(shapes), 5000):
            part = rasterize(shapes[s:s + 5000], out_shape=(self.ny, self.nx), transform=self.tf, fill=0, dtype=dtype,
                             all_touched=all_touched)
            out = np.where(part > 0, part, out)
        return out


NB = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
      (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2))]


def search(block: np.ndarray, target: np.ndarray, start, max_cells: float, slack_cells: float, clear: set):
    """start 칸에서 Dijkstra. 가장 가까운 목표 칸 거리 + slack 안의 목표 칸들 [(거리, 칸, 목표 번호)], 이전 칸."""
    ny, nx = block.shape
    blocked = lambda r, c: block[r, c] and (r, c) not in clear  # noqa: E731
    dist, prev, found, best = {start: 0.0}, {}, [], None
    pq = [(0.0, start)]
    while pq:
        d, (r, c) = heapq.heappop(pq)
        if d > dist.get((r, c), math.inf):
            continue
        if d > max_cells or (best is not None and d > best + slack_cells):
            break
        t = int(target[r, c])
        if t:
            found.append((d, (r, c), t - 1))
            best = d if best is None else best
            continue  # 길에 닿으면 그 너머로 퍼지지 않는다
        for dr, dc, w in NB:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < ny and 0 <= cc < nx) or blocked(rr, cc):
                continue
            if dr and dc and blocked(r + dr, c) and blocked(r, c + dc):
                continue  # 대각선으로 벽 틈을 빠지지 않게
            nd = d + w
            if nd < dist.get((rr, cc), math.inf):
                dist[(rr, cc)] = nd
                prev[(rr, cc)] = (r, c)
                heapq.heappush(pq, (nd, (rr, cc)))
    return found, prev


def free_line(grid: Grid, block: np.ndarray, a, b, clear: set) -> bool:
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    for t in np.linspace(0.0, 1.0, max(2, int(L / (grid.cell * 0.4)) + 1)):
        r, c = grid.rc(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        if not (0 <= r < block.shape[0] and 0 <= c < block.shape[1]):
            return False
        if block[r, c] and (r, c) not in clear:
            return False
    return True


def pull(grid: Grid, block: np.ndarray, pts, clear: set):
    """줄 당기기: 직선으로 갈 수 있는 가장 먼 점까지 건너뛴다."""
    out, i = [pts[0]], 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not free_line(grid, block, pts[i], pts[j], clear):
            j -= 1
        out.append(pts[j])
        i = j
    return out


# ---------------------------------------------------------------- 만들기

def build(graph_path: Path = gp.GRAPH, entrances: Path = gp.ENTRANCES, topo: Path = TOPO, dem_dir: Path = DATA / "dem",
          patch_files=None, out_path: Path = OUT, dorms: Path = gp.DORMS) -> dict:
    from shapely.geometry import LineString, Point, shape
    from shapely.ops import transform as shapely_transform
    from shapely.strtree import STRtree

    proj = be.LocalProj()
    if patch_files is None:
        patch_files = [p for p in sorted(gp.PATCH_DIR.glob("*.geojson")) if p.resolve() != Path(out_path).resolve()]
    graph = base_graph(graph_path, patch_files)
    ents, skipped = entrance_list(entrances, patch_files, skip=gp.label_only(dorms))

    # 같은 자리 출입구는 하나로
    doors = []
    for e in ents:
        q = np.ravel(proj.fwd(e["lon"], e["lat"]))
        lim = {"max_links": int(e.get("max_links", MAX_LINKS)), "slack": float(e.get("slack", SLACK)),
               "clear": float(e.get("clear", 0.0))}
        for d in doors:
            if np.hypot(*(q - d["xy"])) <= 0.05:
                d["ids"].append(f"{e['building']}#{e['no']}")
                d["max_links"], d["slack"] = min(d["max_links"], lim["max_links"]), min(d["slack"], lim["slack"])
                d["clear"] = max(d["clear"], lim["clear"])
                break
        else:
            doors.append({"xy": q, "lon": e["lon"], "lat": e["lat"], "building": e["building"],
                          "ids": [f"{e['building']}#{e['no']}"], **lim})

    # 접속 대상: 걸을 수 있는 엣지(가장 큰 연결 요소), 다른 출입구 접속선·막은 엣지 제외
    nxy = {n["id"]: np.ravel(proj.fwd(n["lng"], n["lat"])) for n in graph["nodes"]}
    seg = {}
    for e in graph["edges"]:
        if not e.get("walkable", True) or e["from"] == e["to"] or e.get("blocked") or e.get("role") == "entrance_link":
            continue
        seg.setdefault((min(e["from"], e["to"]), max(e["from"], e["to"])), e)
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    ids = sorted({i for k in seg for i in k})
    pos = {i: k for k, i in enumerate(ids)}
    a = np.array([pos[u] for u, v in seg])
    b = np.array([pos[v] for u, v in seg])
    _, lab = connected_components(csr_matrix((np.ones(len(a)), (a, b)), shape=(len(ids), len(ids))), directed=False)
    main = np.bincount(lab).argmax()
    keys = [k for k in seg if lab[pos[k[0]]] == main]
    seglen = {k: float(np.hypot(*(nxy[k[0]] - nxy[k[1]]))) for k in keys}
    ka = np.array([pos[u] for u, v in keys])
    kb = np.array([pos[v] for u, v in keys])
    kd = np.array([seglen[k] for k in keys])
    net = csr_matrix((np.concatenate([kd, kd]), (np.concatenate([ka, kb]), np.concatenate([kb, ka]))), shape=(len(ids), len(ids)))

    q_all = np.array([d["xy"] for d in doors])
    pad = MAX_DIST + 20.0
    box = (q_all[:, 0].min() - pad, q_all[:, 1].min() - pad, q_all[:, 0].max() + pad, q_all[:, 1].max() + pad)
    grid = Grid(box)

    dirs = sheet_dirs(topo)
    build_feats = read_layer(dirs, BUILDING, proj)
    solid = [g for g, at in build_feats if at.get("종류") != "무벽건물"]
    shapes = [(g, 1) for g in solid]
    n_bar = 0
    for layer, ok in BARRIERS.items():
        for g, at in read_layer(dirs, layer, proj):
            if ok(at):
                shapes.append((g.buffer(WALL_HALF, cap_style="flat"), 2))
                n_bar += 1
    n_manual = 0
    for f in gp.read_patches(patch_files):  # 패치의 type = barrier: 수치지형도에 없는 장애물(사진으로 본 화단·울타리·단차)
        if (f.get("properties") or {}).get("type") != "barrier" or not f.get("geometry"):
            continue
        g = shapely_transform(lambda x, y, z=None: proj.fwd(x, y), shape(f["geometry"]))
        shapes.append((g if g.geom_type in ("Polygon", "MultiPolygon") else g.buffer(WALL_HALF, cap_style="flat"), 2))
        n_manual += 1
    block = grid.burn(shapes)
    stairs = [g for g, _ in read_layer(dirs, STAIRS, proj)]
    stree = STRtree(stairs) if stairs else None
    # 터널·다리(isTunnel)는 접속 대상에서 뺀다(땅 위 출입구를 지하 통로 가운데에 붙이지 않는다). 연결 요소 계산에는 남긴다
    near = [k for k in keys if not seg[k].get("isTunnel")
            and min(np.hypot(*(q_all - nxy[k[0]]).T).min(), np.hypot(*(q_all - nxy[k[1]]).T).min())
            <= pad + float(np.hypot(*(nxy[k[0]] - nxy[k[1]])))]
    target = grid.burn([(LineString([nxy[u], nxy[v]]).buffer(0.3), i + 1) for i, (u, v) in enumerate(near)],
                       dtype="int32", all_touched=True)
    stree_solid = STRtree(solid)

    dem = None
    paths = [p for p in be.dem_paths([str(dem_dir)]) if p.exists()] if dem_dir else []
    if paths:
        lon_, lat_ = proj.inv(q_all[:, 0], q_all[:, 1])
        dem = be.Dem(paths, bbox=(float(np.min(lat_)) - 0.002, float(np.min(lon_)) - 0.002,
                                  float(np.max(lat_)) + 0.002, float(np.max(lon_)) + 0.002))
        dem.layers = [L for L in dem.layers if abs(L.res[0]) <= 5.0] or None
        dem = dem if dem.layers else None

    def zs(pts):
        if dem is None:
            return np.full(len(pts), np.nan)
        pts = np.atleast_2d(pts)
        lon, lat = proj.inv(pts[:, 0], pts[:, 1])
        return np.asarray(dem.sample(np.atleast_1d(lon), np.atleast_1d(lat)), float)

    ll = lambda p: [round(float(v), 7) for v in proj.inv(p[0], p[1])]  # noqa: E731
    from scipy.sparse.csgraph import dijkstra

    def net_dist(o, c) -> float:
        """두 접점(엣지 위 점) 사이 그래프 거리(NET_LIMIT m까지, 넘으면 inf)."""
        (u1, v1), t1 = o["seg"], o["t"]
        (u2, v2), t2 = c["seg"], c["t"]
        L1, L2_ = seglen[(u1, v1)], seglen[(u2, v2)]
        if (u1, v1) == (u2, v2):
            return abs(t1 - t2) * L1
        D = dijkstra(net, directed=False, indices=[pos[u1], pos[v1]], limit=NET_LIMIT)
        best = math.inf
        for i, off1 in enumerate((t1 * L1, (1 - t1) * L1)):
            for node, off2 in ((u2, t2 * L2_), (v2, (1 - t2) * L2_)):
                best = min(best, off1 + D[i, pos[node]] + off2)
        return best
    feats, unlinked, stats = [], [], defaultdict(int)
    for d in doors:
        q = d["xy"]
        qp = Point(q)
        depth = max([g.boundary.distance(qp) for g in (solid[int(i)] for i in stree_solid.query(qp)) if g.contains(qp)],
                    default=0.0)
        r0, c0 = grid.rc(*q)
        rad = max(depth + 1.0, d["clear"])  # clear: 필로티·처마 밑 출입구(윤곽 깊이 안쪽의 문)에서 건물 칸을 지나갈 수 있는 반경
        n = int(math.ceil(rad / grid.cell)) + 1
        clear = set()
        for dr in range(-n, n + 1):
            for dc in range(-n, n + 1):
                rr, cc = r0 + dr, c0 + dc
                if 0 <= rr < grid.ny and 0 <= cc < grid.nx and block[rr, cc]:
                    dist_ = math.hypot(dr, dc) * grid.cell
                    if (block[rr, cc] == 1 and dist_ <= rad) or dist_ <= DOOR_CLEAR:
                        clear.add((rr, cc))
        found, prev = search(block, target, (r0, c0), MAX_DIST / grid.cell, d["slack"] / grid.cell, clear)
        per = {}
        for dd, cell, si in found:
            if si not in per or dd < per[si][0]:
                per[si] = (dd, cell)
        chosen = []
        for dd, cell, si in sorted((v[0], v[1], si) for si, v in per.items()):
            u, v = near[si]
            A, B = nxy[u], nxy[v]
            cx, cy = grid.xy(*cell)
            ab = B - A
            L2 = float(ab @ ab)
            t = 0.0 if L2 == 0 else float(np.clip(((cx - A[0]) * ab[0] + (cy - A[1]) * ab[1]) / L2, 0.0, 1.0))
            foot = A + ab * t
            if any(np.hypot(*(foot - o["foot"])) < SPACING for o in chosen):
                continue
            cells = [cell]
            while cells[-1] in prev:
                cells.append(prev[cells[-1]])
            cells.reverse()
            pts = [tuple(q)] + [grid.xy(*c) for c in cells[1:-1]] + [tuple(foot)]
            line = LineString(pull(grid, block, pts, clear))
            c = {"foot": foot, "line": line, "seg": (u, v), "t": t}
            # 이미 고른 접속선으로 들어가 길을 따라 가는 것보다 USEFUL m 넘게 짧을 때만 더한다(나란한 군더더기 접속선 빼기)
            if chosen and not all(o["line"].length + net_dist(o, c) > line.length + USEFUL for o in chosen):
                continue
            chosen.append(c)
            if len(chosen) >= d["max_links"]:
                break
        if not chosen:
            unlinked.append(d)
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(d["lon"], 7), round(d["lat"], 7)]},
                          "properties": {"type": "entrance_unlinked", "building": d["building"], "entrances": d["ids"],
                                         "source": LINK_SOURCE,
                                         "note": f"{MAX_DIST:g} m 안에 막히지 않고 닿는 길이 없다(손으로 그릴 것)"}})
            continue
        for c in chosen:
            line = c["line"]
            s = np.arange(0.0, line.length + 1e-9, 2.0)
            pp = np.array([line.interpolate(v).coords[0] for v in s]) if len(s) > 1 else np.array(line.coords)
            z = zs(pp)
            mg = 0.0
            for i in range(len(s)):
                j = int(np.searchsorted(s, s[i] + 6.0))
                if j < len(s) and np.isfinite(z[i]) and np.isfinite(z[j]):
                    mg = max(mg, abs(z[j] - z[i]) / (s[j] - s[i]))
            dz = float(z[-1] - z[0]) if len(z) and np.isfinite(z[0]) and np.isfinite(z[-1]) else 0.0
            on_stairs = stree is not None and any(stairs[int(i)].intersection(line).length > 1.0 for i in stree.query(line))
            check = [w for w, on in (("long", line.length > LONG), ("steep", mg > STEEP and abs(dz) > 2.0),
                                     ("deep", depth > DEEP)) if on]
            for w in check:
                stats[w] += 1
            kind = "steps" if on_stairs else "footway"
            feats.append({"type": "Feature",
                          "geometry": {"type": "LineString", "coordinates": [ll(p) for p in line.coords]},
                          "properties": {k: v for k, v in {
                              "type": "path", "role": "entrance_link", "building": d["building"], "entrances": d["ids"],
                              "source": LINK_SOURCE,
                              "kind": kind, "costFactor": 1.2 if kind == "steps" else 1, "snap": 0.5, "link": 1.0,
                              "length_m": round(line.length, 1), "straight_m": round(float(np.hypot(*(c["foot"] - q))), 1),
                              "detour": len(line.coords) > 2 or None, "max_grade": round(mg * 100) if mg else None,
                              "door_depth_m": round(depth, 1) if depth > 0.05 else None,
                              "door_clear_m": d["clear"] or None,
                              "check": check or None}.items() if v is not None}})
            stats["links"] += 1
    fc = {"type": "FeatureCollection",
          "meta": {"source": SOURCE, "cell_m": CELL, "max_dist_m": MAX_DIST, "slack_m": SLACK, "spacing_m": SPACING,
                   "barriers": sorted(BARRIERS), "skipped": skipped,
                   "note": "role = entrance_link 의 첫 점이 출입구 노드(graph_patch.apply_patch), slope_travel.py 가 거기서 출발한다"},
          "features": feats}
    fc["meta"]["stats"] = {"doors": len(doors), "links": stats["links"], "unlinked": len(unlinked),
                           "barrier_lines": n_bar, "patch_barriers": n_manual, "buildings": len(solid), **{k: stats[k] for k in ("long", "steep", "deep")}}
    return fc


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=str(OUT))
    ap.add_argument("--patch-dir", default=str(gp.PATCH_DIR), help="다른 패치 파일(길·출입구)을 읽을 폴더")
    ap.add_argument("--report", action="store_true", help="확인이 필요한 접속선 목록")
    args = ap.parse_args(argv)
    out = Path(args.output)
    others = [p for p in sorted(Path(args.patch_dir).glob("*.geojson")) if p.resolve() != out.resolve()]
    fc = build(out_path=out, patch_files=others)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fc, ensure_ascii=False, indent=1), encoding="utf-8")
    s = fc["meta"]["stats"]
    links = [f["properties"] for f in fc["features"] if f["properties"].get("role") == "entrance_link"]
    L = np.array([p["length_m"] for p in links]) if links else np.zeros(1)
    print(f"저장: {out}")
    print(f"  출입구 {s['doors']}곳 · 접속선 {s['links']}개(길이 중앙값 {np.median(L):.1f} m, 90 % {np.percentile(L, 90):.1f} m,"
          f" 돌아가는 선 {sum(1 for p in links if p.get('detour'))}개) · 못 이은 출입구 {s['unlinked']}곳")
    print(f"  수치지형도: 건물 {s['buildings']:,}개, 장애물 선 {s['barrier_lines']:,}개 · 확인 필요: 긴 선 {s['long']}, 가파름 {s['steep']},"
          f" 윤곽 깊이 안 출입구 {s['deep']}")
    if args.report:
        for f in fc["features"]:
            p = f["properties"]
            if p.get("check") or p["type"] == "entrance_unlinked":
                print("  ", ",".join(p["entrances"]), p.get("check") or "못 이음", p.get("length_m", ""), p.get("max_grade", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
