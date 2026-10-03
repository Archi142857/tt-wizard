"""도로 그래프 보강: data/graph_patch/*.geojson 을 받은 그래프에 더하는 함수(apply_patch)와, 기숙사 둘레 OSM 길 → dorm.geojson

  python scripts/graph_patch.py              # 다시 만들면 dorm.geojson 을 덮어쓴다(손으로 고칠 것은 같은 폴더의 다른 파일에)

캠퍼스 마법 지도 도로 그래프(data/magicmap/roads_graph_updated.json)는 받은 자료라 고치지 않는다. 더할 것·막을 것만 data/graph_patch/ 의
GeoJSON 에 두고, graph_slopes.py 가 apply_patch 로 그래프에 더한 뒤 경사를 붙인다(더한 노드·엣지는 src = "ttwizard").
마법 지도 개발자는 그래프를 OSM·국토지리정보원 자료·사용자 제보·네이버 지도로 만들었다고 했다. 파일과 피처 형식은 data/graph_patch/README.md.

패치 파일 (이름순으로 읽는다. 접속선은 어느 파일에 있든 길을 다 더한 뒤에 붙인다)
  campus.geojson    관악캠 전체 점검(2026-10): 출입구(replace = true), 더한 길, 막은 엣지(type = block), 장애물 선(type = barrier)
  dorm.geojson      이 스크립트가 만든다(아래 '길'·'출입구')
  gwanaksa.geojson  관악학생생활관 둘레를 1:1,000 수치지형도·위성 사진으로 그린 길(type = area 안)
  links.geojson     entrance_links.py 가 만드는 출입구 접속선

apply_patch 가 하는 일
  막기      type = block 의 [노드, 노드] 엣지에 blocked 를 단다(실제로 없는 길. 경로·잇기·접속선이 쓰지 않는다)
  갈림목    받은 그래프에서 다른 엣지 위(JUNCTION_TOL m 안)에 찍혀 있는데 이어져 있지 않은 노드를 그 엣지를 따라 잇는다(heal_junctions)
  길        꼭짓점마다 노드, 이웃 사이 양방향 엣지. 끝은 가까운 노드(snap m)나 엣지 위 수선의 발(link m)에 잇는다. 중간 꼭짓점이
            이미 있는 노드와 VERTEX_TOL m 안이면 그 노드를 쓰고, 붙을 곳이 없던 끝은 길을 다 더한 뒤 다시 붙여 본다
  접속선    role = entrance_link: 첫 점이 출입구 노드(building, entrance = true), 끝 점만 길에 붙인다
  터널·다리(isTunnel) 엣지 가운데와 막은 엣지에는 아무것도 붙이지 않는다

dorm.geojson 만들기 (build)
길      기숙사 동(data/dorm_buildings.csv) 윤곽 둘레 ZONE m 안의 OSM 길(footway·path·steps·pedestrian·service) 중
        그래프에서 GAP m 넘게 떨어진 부분(MIN_RUN m 이상). 차도 옆 보도(GAP 안)는 차도 엣지로 친다. 캠퍼스 밖 동네 길(낙성대로 등)은 뺀다.
        광장 테두리(닫힌 pedestrian)·실내 길은 뺀다. 끝은 graph_slopes 가 가까운 노드(SNAP m)나 엣지(LINK m)에 잇는다
출입구  이동시간을 내는 동(travel = Y)마다 building_entrances.csv → OSM 출입구 노드(벽 3 m 안) → 벽에 닿는 마법 지도 그래프의
        막다른 끝(6 m 안) → 벽에 닿는 위 길의 끝(3 m 안) → 없으면 가장 가까운 길 쪽 벽 한 점(추정).
        다른 파일에 replace = true 출입구가 있는 동(손으로 확인한 것)과 type = area 안의 동은 만들지 않는다.
        출입구에서 길까지 접속선은 scripts/entrance_links.py 가 모든 출입구에 대해 links.geojson 에 만든다(건물·담장·옹벽을 피한 선)
출처    properties.source 에 적는다. 동 윤곽은 OSM(이름 = 동 번호, 글로벌학생생활관(915), BK국제관)
손으로 그린 패치  같은 폴더의 다른 파일에 type = area 다각형이 있으면 그 안에서는 OSM 길·출입구를 자동으로 만들지 않는다(그 파일의 길·출입구가
        대신한다). 길 properties 의 snap·link(m)는 그 길 끝을 그래프에 붙일 거리(없으면 SNAP·LINK). 손으로 그린 길은 작게(0.5·1 m) 둬서
        정확히 노드 위·엣지 위에 둔 끝만 붙는다
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import building_elevation as be  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GRAPH = DATA / "magicmap" / "roads_graph_updated.json"
OSM_PATHS = DATA / "osm_paths.geojson"
OSM_BUILDINGS = DATA / "osm_buildings.geojson"
OSM_ENTRANCES = DATA / "osm_entrances.geojson"
DORMS = DATA / "dorm_buildings.csv"
ENTRANCES = DATA / "building_entrances.csv"
PATCH_DIR = DATA / "graph_patch"
OUT = PATCH_DIR / "dorm.geojson"

ZONE = 60.0     # 기숙사 동 윤곽 둘레(m)
GAP = 8.0       # 그래프에서 이만큼 넘게 떨어진 OSM 길만 '없는 길'
MIN_RUN = 15.0  # 없는 길 조각의 최소 길이(m)
SNAP = 3.0      # 길 끝이 이 안의 그래프 노드면 그 노드에 잇는다
LINK = 20.0     # 아니면 이 안의 그래프 엣지에 수선을 내려 잇는다
JUNCTION_TOL = 0.3  # 받은 그래프의 노드가 다른 엣지에서 이 안이면 그 엣지 위에 찍힌 갈림목으로 보고 잇는다(m)
JUNCTION_END = 0.5  # 엣지 끝에서 이 안이면 끝 노드 자리라 따로 잇지 않는다(m)
VERTEX_TOL = 0.3    # 길의 중간 꼭짓점이 이미 있는 노드에서 이 안이면 그 노드를 쓴다(m): 먼저 더한 길의 끝과 같은 자리를 지나는 길을 잇는다
# OSM highway → (그래프 kind, costFactor). 마법 지도 그래프의 kind 별 값과 같게. 캠퍼스 밖 동네 길(residential 등)은 더하지 않는다
KIND = {"footway": ("footway", 1), "path": ("footway", 1), "pedestrian": ("footway", 1), "steps": ("steps", 1.2),
        "service": ("service", 1.05)}
SOURCE = "OSM(© OpenStreetMap contributors, ODbL)·국토지리정보원 수치지형도 건물 번호로 tt-wizard 가 더함"
PATCH_NOTE = ("src = ttwizard 인 노드·엣지: tt-wizard 가 data/graph_patch/*.geojson 을 더한 것(scripts/graph_patch.py). "
              "role = junction 은 받은 그래프에서 엣지 위에 찍혀 있던 노드를 그 엣지와 이은 조각, role = entrance_link 는 건물 출입구에서 "
              "길까지의 접속선(entrance = true 노드가 출입구). 길·출입구는 OSM(© OpenStreetMap contributors, ODbL), 국토지리정보원 "
              "1:1,000 수치지형도(2025), 카카오맵 로드뷰·스카이뷰로 확인한 것(2026-10 관악캠 점검). 받은 엣지의 blocked 는 "
              "실제로 없다고 본 길(건물을 지나는 선, 공사 구역)이고 그 밖의 값은 받은 그대로다")


def _rows(path: Path) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _features(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8")).get("features", []) if Path(path).exists() else []


def read_patches(paths) -> list[dict]:
    """data/graph_patch/*.geojson(또는 준 파일들)의 피처를 모두."""
    out = []
    for p in paths:
        p = Path(p)
        for q in (sorted(p.glob("*.geojson")) if p.is_dir() else [p]):
            out += _features(q)
    return out


def patch_entrances(paths) -> dict[str, list[tuple[float, float]]]:
    """패치의 출입구(Point, properties.building) → {동: [(lon, lat)]}. replace = true 인 출입구(사용자 제보)가 있는 동은 그것만."""
    out, only = defaultdict(list), defaultdict(list)
    for f in read_patches(paths):
        p, g = f.get("properties") or {}, f.get("geometry") or {}
        if p.get("type") == "entrance" and g.get("type") == "Point" and p.get("building"):
            pt = tuple(map(float, g["coordinates"][:2]))
            (only if p.get("replace") else out)[str(p["building"])].append(pt)
    out.update(only)
    return dict(out)


def label_only(path: Path = DORMS) -> set[str]:
    """기숙사 동 목록에서 travel = N 인 동: 지도에 번호만 남기고 이동시간·출입구는 쓰지 않는다(919 → 919A~D 네 동이 대신한다)."""
    return {r["building"].strip() for r in _rows(path) if (r.get("travel") or "").strip().upper() == "N"}


def reported_entrances(paths) -> dict[str, list[tuple[float, float]]]:
    """replace = true 인 출입구(사용자 제보·손으로 그린 패치)만 → {동: [(lon, lat)]}. building_entrances.csv 보다 우선한다."""
    out = defaultdict(list)
    for f in read_patches(paths):
        p, g = f.get("properties") or {}, f.get("geometry") or {}
        if p.get("type") == "entrance" and p.get("replace") and g.get("type") == "Point" and p.get("building"):
            out[str(p["building"])].append(tuple(map(float, g["coordinates"][:2])))
    return dict(out)


def curated_areas(features) -> list:
    """type = area 다각형(손으로 그린 패치가 맡는 곳) → shapely 다각형(경위도) 목록."""
    from shapely.geometry import shape

    return [shape(f["geometry"]) for f in features
            if (f.get("properties") or {}).get("type") == "area" and (f.get("geometry") or {}).get("type") in ("Polygon", "MultiPolygon")]


# ---------------------------------------------------------------- 그래프에 더하기 (graph_slopes.py 가 부른다, numpy 만)

def _pair(e: dict) -> tuple[int, int]:
    return (min(e["from"], e["to"]), max(e["from"], e["to"]))


def _walk_segments(nodes_xy: dict, edges: list[dict]):
    """걸을 수 있는 엣지 → 방향 없는 구간 {(u, v): 대표 엣지}. 막은 엣지와 터널·다리(isTunnel)는 뺀다
    (땅 위의 길·접속선을 지하 통로 가운데에 붙이지 않는다. 터널 끝 노드에는 snap 으로 붙을 수 있다)."""
    seg = {}
    for e in edges:
        if not e.get("walkable", True) or e["from"] == e["to"] or e.get("blocked") or e.get("isTunnel"):
            continue
        seg.setdefault(_pair(e), e)
    return seg


def apply_blocks(graph: dict, features: list[dict]) -> int:
    """type = block 피처: properties.edges 의 [노드, 노드] 쌍을 잇는 엣지(양방향)에 blocked = 이유 를 단다.
    받은 값(walkable 등)은 그대로 두고, 경로 계산(slope_travel)·패치 잇기·출입구 접속선이 이 엣지를 쓰지 않는다.
    현장·로드뷰·수치지형도로 실제로 없는 길(건물·담장을 뚫는 선 등)이라고 본 것만. 쌍은 받은 그래프의 노드 번호로 적는다.

    끊긴 갈림목을 이은 조각(heal_junctions, role = junction)과 맞물리는 경우:
    - 조각 [n1, n2] 를 막으면 그 조각이 나온 원래 엣지(split_of)도 막는다(원래 엣지가 남으면 그 구간을 그대로 지나간다).
      같은 엣지의 다른 조각은 남는다(엣지의 한쪽만 막을 때 쓴다)
    - 원래 엣지 [u, v] 를 막으면 그 엣지의 조각도 모두 막는다"""
    listed = {}
    for f in features:
        p = f.get("properties") or {}
        if p.get("type") != "block":
            continue
        why = p.get("note") or p.get("source") or "blocked"
        for u, v in p.get("edges") or []:
            listed[(min(int(u), int(v)), max(int(u), int(v)))] = why
    if not listed:
        return 0
    edges = graph["edges"]
    by_id = {e["id"]: e for e in edges}
    origin = {}  # 조각 엣지 번호 → 원래 엣지 쌍
    for e in edges:
        if e.get("role") == "junction" and e.get("split_of") in by_id:
            origin[e["id"]] = _pair(by_id[e["split_of"]])
    pairs = dict(listed)
    for e in edges:  # 막은 조각의 원래 엣지
        if e["id"] in origin and _pair(e) in listed:
            pairs.setdefault(origin[e["id"]], listed[_pair(e)])
    n = 0
    for e in edges:
        k = _pair(e)
        why = pairs.get(k) or (listed.get(origin[e["id"]]) if e["id"] in origin else None)
        if why:
            e["blocked"] = why
            n += 1
    return n


def heal_junctions(graph: dict, proj: be.LocalProj | None = None, tol: float = JUNCTION_TOL) -> set[tuple[int, int]]:
    """받은 그래프에서 노드가 다른 엣지 '위'에 찍혀 있는데(tol m 안) 그 엣지와 이어져 있지 않은 갈림목을 잇는다.

    마법 지도 그래프에 나중에 더해진 길(노드 8,900번대 이후)은 끝이 기존 엣지 위에 놓여 있지만 그 엣지가 나뉘지 않아
    본체와 끊겨 있다(끊긴 조각 51개·3.3 km 중 33개·2.6 km 가 이런 끝). 엣지 위 노드를 엣지를 따라 차례로 이어
    u – n1 – n2 – … – v 조각 엣지를 더한다(src = "ttwizard", role = "junction", split_of = 원래 엣지 번호).
    받은 노드·엣지는 그대로 둔다. 터널·다리(isTunnel)·막은(blocked) 엣지에는 잇지 않고(위아래로 엇갈릴 수 있다),
    이미 이어진 이웃끼리는 더하지 않는다. 위에 노드가 놓인 원래 엣지 {(u, v)} 를 돌려준다(패치 길·접속선은 그 엣지 말고 조각에 붙인다.
    받은 그래프에는 엣지 위에 노드를 찍고 양 끝과 따로 이어 둔 곳이 있어(노드 9182~9193), 원래 엣지에 붙이면 그 노드로 바로 못 간다)."""
    proj = proj or be.LocalProj()
    nodes, edges = graph["nodes"], graph["edges"]
    X, Y = proj.fwd(np.array([n["lng"] for n in nodes], float), np.array([n["lat"] for n in nodes], float))
    xy = {n["id"]: (float(x), float(y)) for n, x, y in zip(nodes, np.ravel(X), np.ravel(Y))}
    seg, adj = {}, defaultdict(set)
    for e in edges:
        if not e.get("walkable", True) or e["from"] == e["to"] or e.get("blocked"):
            continue
        adj[e["from"]].add(e["to"])
        adj[e["to"]].add(e["from"])
        if not e.get("isTunnel"):
            seg.setdefault(_pair(e), e)
    cell = 25.0
    grid = defaultdict(list)
    for k in seg:
        (ax, ay), (bx, by) = xy[k[0]], xy[k[1]]
        for cx in range(int(math.floor((min(ax, bx) - tol) / cell)), int(math.floor((max(ax, bx) + tol) / cell)) + 1):
            for cy in range(int(math.floor((min(ay, by) - tol) / cell)), int(math.floor((max(ay, by) + tol) / cell)) + 1):
                grid[(cx, cy)].append(k)
    on = defaultdict(list)  # 엣지 → [(엣지를 따라 잰 거리, 노드)]
    for n in adj:
        x, y = xy[n]
        for k in grid.get((int(math.floor(x / cell)), int(math.floor(y / cell))), ()):
            if n in k:
                continue
            (ax, ay), (bx, by) = xy[k[0]], xy[k[1]]
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy)
            if L < 2 * JUNCTION_END:
                continue
            along = ((x - ax) * dx + (y - ay) * dy) / L
            if along < JUNCTION_END or along > L - JUNCTION_END or abs((x - ax) * dy - (y - ay) * dx) / L > tol:
                continue
            on[k].append((along, n))
    next_edge = max(e["id"] for e in edges) + 1
    split = set()
    for k in sorted(on):
        e = seg[k]
        chain = [k[0]] + [n for _, n in sorted(on[k])] + [k[1]]
        for a, b in zip(chain[:-1], chain[1:]):
            if a == b or b in adj[a]:
                continue
            d = float(math.hypot(xy[b][0] - xy[a][0], xy[b][1] - xy[a][1]))
            for u, v in ((a, b), (b, a)):
                edges.append({"id": next_edge, "from": u, "to": v, "distance": round(d, 3), "kind": e.get("kind", "footway"),
                              "oneway": False, "walkable": True, "costFactor": e.get("costFactor", 1), "isTunnel": False,
                              "src": "ttwizard", "role": "junction", "split_of": e["id"]})
                next_edge += 1
            adj[a].add(b)
            adj[b].add(a)
        split.add(k)  # 조각이 이미 다 있어도(받은 그래프가 엣지 위 노드를 양 끝과 따로 이어 둔 곳) 원래 엣지에는 붙이지 않는다
    return split


def apply_patch(graph: dict, features: list[dict], proj: be.LocalProj | None = None,
                snap: float = SNAP, link: float = LINK) -> dict:
    """패치의 길(LineString)을 그래프에 더한다(그래프를 고쳐서 돌려준다). 받은 노드·엣지는 그대로 두고 더하기만 한다.

    - 길의 꼭짓점마다 새 노드, 이웃 꼭짓점 사이 양방향 엣지(distance = 직선 거리, src = "ttwizard", osm = way 번호)
    - 길의 두 끝: snap m 안에 그래프 노드가 있으면 그 노드를 쓴다. 없고 link m 안에 걸을 수 있는 엣지가 있으면 그 위 수선의 발에
      새 노드를 두고 엣지 양 끝과 잇는다(split_of = 원래 엣지 번호, 원래 엣지는 그대로) + 길 끝과 수선의 발을 잇는다(kind 는 길과 같게)
    - 길끼리도 먼저 더한 길에 이어진다. 길 끝은 같은 길의 다른 끝에는 붙지 않는다. 붙일 곳이 없던 끝은 길을 다 더한 뒤 한 번 더
      붙여 본다(뒤에 읽은 패치 파일의 길에 닿는 끝. 접속선은 그 뒤에 붙인다)
    - 길의 중간 꼭짓점: VERTEX_TOL m 안에 이미 노드(받은 노드, 먼저 더한 길의 끝·꼭짓점)가 있으면 그 노드를 쓴다. 출입구 노드는 빼고
      (다른 파일의 길이 먼저 더한 길의 끝과 같은 자리를 지날 때 두 길이 이어지게)
    - 길 properties 에 snap·link(m)가 있으면 그 길은 그 값으로 붙인다(손으로 그린 길: 0.5·1 m)
    - 같은 엣지에 여러 번 붙으면 이미 나눈 조각을 다시 나눈다(조각끼리 이어진다)
    - 그 전에 받은 그래프의 끊긴 갈림목을 잇는다(heal_junctions). features 가 비어 있어도 한다
    """
    proj = proj or be.LocalProj()
    apply_blocks(graph, features)  # 막은 엣지에는 갈림목·길·접속선을 붙이지 않는다
    split = heal_junctions(graph, proj)  # 엣지 위에 찍힌 갈림목을 먼저 잇는다(패치 길은 그 조각에 붙는다)
    apply_blocks(graph, features)  # 조각을 가리킨 block(엣지의 한쪽만 막기)은 조각이 생긴 뒤에 걸린다
    nodes, edges = graph["nodes"], graph["edges"]
    xy = {}
    for n in nodes:
        x, y = proj.fwd(n["lng"], n["lat"])
        xy[n["id"]] = (float(x), float(y))
    seg = _walk_segments(xy, edges)
    for k in split:  # 조각으로 나뉜 원래 엣지는 붙일 후보에서 뺀다(그래프에는 그대로 남는다)
        seg.pop(k, None)
    next_node = max(n["id"] for n in nodes) + 1
    next_edge = max(e["id"] for e in edges) + 1
    cells = defaultdict(list)  # 0.5 m 칸 → 노드(중간 꼭짓점이 이미 있는 노드와 같은 자리인지 볼 때)
    door_nodes = set()         # 출입구 노드: 길의 꼭짓점을 여기에 합치지 않는다(출입구는 지나가는 길이 아니다)
    ground = {n for e in edges if not e.get("isTunnel") for n in (e["from"], e["to"])}
    under = {n for e in edges if e.get("isTunnel") for n in (e["from"], e["to"])} - ground  # 지하 통로 안쪽 노드에도 합치지 않는다

    def _cell(x, y):
        return int(math.floor(x / 0.5)), int(math.floor(y / 0.5))

    for i, (x, y) in xy.items():
        cells[_cell(x, y)].append(i)

    def new_node(x, y, **tags):
        nonlocal next_node
        lon, lat = proj.inv(x, y)
        n = {"id": next_node, "lng": round(float(lon), 8), "lat": round(float(lat), 8), "src": "ttwizard", **tags}
        nodes.append(n)
        xy[next_node] = (float(x), float(y))
        cells[_cell(x, y)].append(next_node)
        if tags.get("entrance"):
            door_nodes.add(next_node)
        next_node += 1
        return n["id"]

    def vertex(x, y):
        """길의 중간 꼭짓점 노드: VERTEX_TOL 안에 이미 있는 노드(출입구 노드 제외)가 있으면 그 노드, 없으면 새 노드."""
        cx, cy = _cell(x, y)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in cells.get((cx + dx, cy + dy), ()):
                    if i in door_nodes or i in under:
                        continue
                    d = math.hypot(xy[i][0] - x, xy[i][1] - y)
                    if d <= VERTEX_TOL and (best is None or d < best[0]):
                        best = (d, i)
        return best[1] if best else new_node(x, y)

    def new_edge(u, v, kind, cf, extra):
        nonlocal next_edge
        d = float(math.hypot(xy[v][0] - xy[u][0], xy[v][1] - xy[u][1]))
        for a, b in ((u, v), (v, u)):
            edges.append({"id": next_edge, "from": a, "to": b, "distance": round(d, 3), "kind": kind, "oneway": False,
                          "walkable": True, "costFactor": cf, "isTunnel": False, "src": "ttwizard", **extra})
            next_edge += 1
        seg[(min(u, v), max(u, v))] = edges[-1]

    def anchor(x, y, kind, cf, extra, snap=snap, link=link, exclude=(), here=None):
        """(x, y) 를 그래프에 붙일 노드. 못 붙이면 None. exclude: 붙지 않을 노드(같은 길의 다른 끝).
        here: 이미 만든 길 끝 노드를 다시 붙일 때 그 노드(붙은 곳과 엣지로 잇고 here 를 돌려준다. 못 붙이면 None)."""
        ids = np.fromiter((i for i in xy if i not in exclude), int)
        P = np.array([xy[i] for i in ids])
        d = np.hypot(P[:, 0] - x, P[:, 1] - y)
        k = int(np.argmin(d))
        if d[k] <= snap:
            if here is None:
                return int(ids[k])
            new_edge(here, int(ids[k]), kind, cf, {**extra, "connector": True})
            return here
        best = None
        for (u, v), e in seg.items():
            if u in exclude or v in exclude:
                continue
            ax, ay = xy[u]
            bx, by = xy[v]
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else min(1.0, max(0.0, ((x - ax) * dx + (y - ay) * dy) / L2))
            px, py = ax + dx * t, ay + dy * t
            g = math.hypot(x - px, y - py)
            if g <= link and (best is None or g < best[0]):
                best = (g, u, v, e, px, py, t)
        if best is None:
            return None
        g, u, v, e, px, py, t = best
        L = math.hypot(xy[v][0] - xy[u][0], xy[v][1] - xy[u][1])
        if t * L < 0.5 or (1 - t) * L < 0.5:  # 엣지 끝에 붙어 있으면 그 끝 노드
            foot = u if t * L < 0.5 else v
        else:
            foot = here if here is not None and g < 0.5 else new_node(px, py)  # 다시 붙이는 끝이 엣지 위면 그 노드가 수선의 발
            # 나눈 엣지는 찾기 목록에서 빼고 두 조각을 넣는다(같은 엣지에 또 붙을 때 조각을 나누도록). 원래 엣지는 그래프에 그대로
            seg.pop((min(u, v), max(u, v)), None)
            piece = {"split_of": e.get("split_of", e["id"])}
            if e.get("role") == "junction":  # 갈림목 조각을 또 나눈 것: block 이 원래 엣지와 같이 다루게
                piece["role"] = "junction"
            for w in (u, v):
                new_edge(foot, w, e.get("kind", "footway"), e.get("costFactor", 1), piece)
        if here is not None:
            if foot != here:
                new_edge(here, foot, kind, cf, {**extra, "connector": True})
            return here
        if g < 0.5:  # 이미 엣지 위: 수선의 발이 그 점
            return foot
        here = new_node(x, y)
        new_edge(here, foot, kind, cf, {**extra, "connector": True})
        return here

    free = []  # 붙일 곳이 없던 길 끝 (노드, 그 길의 노드들, kind, cf, extra, near)

    def retry_free():
        """붙일 곳을 못 찾았던 길 끝을 길을 다 더한 뒤 다시 붙인다(뒤에 더한 길, 곧 다른 패치 파일의 길에 닿는 끝)."""
        for node, own, kind, cf, extra, near in free:
            anchor(xy[node][0], xy[node][1], kind, cf, extra, **near, exclude=own, here=node)
        free.clear()

    added = 0
    paths = [f for f in features if (f.get("properties") or {}).get("type") == "path"
             and (f.get("geometry") or {}).get("type") == "LineString" and len(f["geometry"].get("coordinates") or []) >= 2]
    paths.sort(key=lambda f: f["properties"].get("role") == "entrance_link")  # 길을 먼저, 출입구 접속선은 그 뒤에
    doors = {}  # 출입구 노드: 같은 자리(5 cm 안)에서 나가는 접속선 여럿은 한 노드를 같이 쓴다
    for f in paths:
        g, p = f["geometry"], f["properties"]
        kind, cf = p.get("kind") or "footway", p.get("costFactor", 1)
        extra = {k: p[k] for k in ("osm", "role", "building") if p.get(k) is not None}
        near = {"snap": float(p.get("snap", snap)), "link": float(p.get("link", link))}
        c = np.asarray(g["coordinates"], float)[:, :2]
        X, Y = proj.fwd(c[:, 0], c[:, 1])
        if p.get("role") == "entrance_link":  # 출입구 쪽 끝은 그대로 두고(건물 노드), 길 쪽 끝만 잇는다
            if free:  # 접속선을 붙이기 전에(길을 다 더한 뒤) 못 붙었던 길 끝을 다시 본다
                retry_free()
            key = (round(float(X[0]) / 0.05), round(float(Y[0]) / 0.05))
            first = doors.get(key)
            if first is None:
                first = doors[key] = new_node(X[0], Y[0], building=str(p.get("building", "")), entrance=True)
        else:
            first = anchor(float(X[0]), float(Y[0]), kind, cf, extra, **near)
        ends = [first, anchor(float(X[-1]), float(Y[-1]), kind, cf, extra, **near,
                              exclude={first} if first is not None else ())]  # 짧은 길이 제 시작 노드에 붙지 않게
        chain = [ends[0] if ends[0] is not None else new_node(X[0], Y[0])]
        for x, y in zip(X[1:-1], Y[1:-1]):
            chain.append(vertex(float(x), float(y)))
        chain.append(ends[1] if ends[1] is not None else new_node(X[-1], Y[-1]))
        for a, b in zip(chain[:-1], chain[1:]):
            if a != b:
                new_edge(a, b, kind, cf, extra)
        if p.get("role") != "entrance_link":
            free += [(chain[j], set(chain), kind, cf, extra, near) for j in (0, -1) if ends[j] is None]
        added += 1
    retry_free()
    graph.setdefault("meta", {})
    if added or split:
        graph["meta"]["patch"] = PATCH_NOTE
    return graph


# ---------------------------------------------------------------- 패치 만들기 (shapely)

def dorm_footprints(ids: set[str], path: Path = OSM_BUILDINGS) -> dict:
    """OSM 건물 윤곽 중 기숙사 동(이름이 동 번호) → {동: shapely 다각형(경위도)}."""
    from shapely.geometry import shape

    out = {}
    for f in _features(path):
        name = ((f.get("properties") or {}).get("name") or "").strip()
        key = "946" if name == "BK국제관" else None
        m = re.fullmatch(r"(?:글로벌학생생활관\()?(\d{3})([A-D])?\)?", name)
        if m:
            key = m.group(1) + (m.group(2) or "")  # OSM 이름 919A → 919A
        if key in ids and key not in out:
            out[key] = shape(f["geometry"])
    return out


def build(graph_path: Path = GRAPH, osm_paths: Path = OSM_PATHS, buildings: Path = OSM_BUILDINGS,
          osm_entrances: Path = OSM_ENTRANCES, dorms: Path = DORMS, entrances: Path = ENTRANCES,
          zone: float = ZONE, gap: float = GAP, min_run: float = MIN_RUN, manual=()) -> dict:
    """manual: 손으로 고친 패치 파일들. 거기 replace = true 출입구가 있는 동은 출입구·접속선을 만들지 않는다(제보가 우선)."""
    from shapely import STRtree, points
    from shapely.geometry import LineString, Point, mapping
    from shapely.ops import substring, transform, unary_union

    proj = be.LocalProj()
    to_m = lambda g: transform(lambda x, y, z=None: proj.fwd(x, y), g)  # noqa: E731
    to_ll = lambda g: transform(lambda x, y, z=None: proj.inv(x, y), g)  # noqa: E731
    rows = _rows(dorms)
    travel = [r["building"] for r in rows if (r.get("travel") or "").upper() == "Y"]
    feet = {k: to_m(v) for k, v in dorm_footprints({r["building"] for r in rows}, buildings).items()}
    area = unary_union(list(feet.values())).buffer(zone)

    graph = json.loads(Path(graph_path).read_text(encoding="utf-8-sig"))
    nxy = {}
    for n in graph["nodes"]:
        x, y = proj.fwd(n["lng"], n["lat"])
        nxy[n["id"]] = (float(x), float(y))
    seg = _walk_segments(nxy, graph["edges"])
    lines = [LineString([nxy[u], nxy[v]]) for u, v in seg]
    tree = STRtree(lines)
    deg = defaultdict(set)
    for u, v in seg:
        deg[u].add(v)
        deg[v].add(u)
    dead = [i for i, s in deg.items() if len(s) == 1]

    # 길: 기숙사 둘레의 OSM 길 중 그래프에서 gap 넘게 떨어진 조각
    runs = []
    for f in _features(osm_paths):
        p, g = f.get("properties") or {}, f.get("geometry") or {}
        hw = p.get("highway")
        if hw not in KIND or g.get("type") != "LineString" or str(p.get("indoor") or "") not in ("", "no"):
            continue
        c = g["coordinates"]
        if hw == "pedestrian" and len(c) > 3 and c[0] == c[-1]:
            continue  # 광장 테두리
        line = to_m(LineString(c))
        if not line.intersects(area):
            continue
        part = line.intersection(area)
        for piece in getattr(part, "geoms", [part]):
            if piece.geom_type != "LineString" or piece.length < min_run:
                continue
            s = np.arange(0.0, piece.length + 1e-9, 2.0)
            pts = points([piece.interpolate(v).coords[0] for v in s])
            _, d = tree.query_nearest(pts, return_distance=True, all_matches=False)
            far = d > gap
            i = 0
            while i < len(s):
                if not far[i]:
                    i += 1
                    continue
                j = i
                while j + 1 < len(s) and far[j + 1]:
                    j += 1
                a, b = s[max(i - 1, 0)], s[min(j + 1, len(s) - 1)]  # 그래프 가까이까지 늘려 끝이 이어지게
                if b - a >= min_run:
                    runs.append((substring(piece, a, b).simplify(0.5), hw, p.get("osm_id"), p.get("name") or ""))
                i = j + 1
    runs.sort(key=lambda r: -r[0].length)
    kept = []
    for r in runs:  # 겹친 OSM 길(같은 보도를 두 번 그린 것)은 하나만
        if kept:
            other = STRtree([k[0] for k in kept])
            pts = points([r[0].interpolate(v).coords[0] for v in np.arange(0.0, r[0].length + 1e-9, 2.0)])
            _, d = other.query_nearest(pts, return_distance=True, all_matches=False)
            if np.mean(d <= 3.0) >= 0.8:
                continue
        kept.append(r)

    # 출입구
    ents_csv = defaultdict(list)
    for r in _rows(entrances):
        if r.get("lat") and r.get("lon"):
            ents_csv[r["building"]].append((float(r["lon"]), float(r["lat"]), r.get("source") or ""))
    osm_ents = [((f.get("properties") or {}).get("osm_id"), tuple(f["geometry"]["coordinates"][:2]))
                for f in _features(osm_entrances) if (f.get("geometry") or {}).get("type") == "Point"]
    manual_feats = read_patches(manual)
    reported = {str((f.get("properties") or {}).get("building")) for f in manual_feats
                if (f.get("properties") or {}).get("type") == "entrance" and (f.get("properties") or {}).get("replace")}
    areas = [to_m(a) for a in curated_areas(manual_feats)]
    kept = [k for k in kept if not any(k[0].intersects(a) for a in areas)]  # 손으로 그린 곳의 길은 그 패치가 맡는다
    run_ends = [(Point(k[0].coords[e]), k[2]) for k in kept for e in (0, -1)]
    all_lines = lines + [k[0] for k in kept]
    all_tree = STRtree(all_lines)
    inside = {r["building"] for r in rows if r.get("lat") and r.get("lon")
              and any(a.contains(Point(*proj.fwd(float(r["lon"]), float(r["lat"])))) for a in areas)}
    entrances_out = []
    for b in travel:
        if b in reported or b in inside:
            continue
        poly = feet.get(b)
        found = [((lon, lat), f"building_entrances.csv({src})") for lon, lat, src in ents_csv.get(b, [])]
        if not found and poly is not None:
            ring = poly.exterior
            for oid, (lon, lat) in osm_ents:
                q = Point(*proj.fwd(lon, lat))
                if poly.buffer(3.0).contains(q):
                    found.append(((lon, lat), f"OSM node {oid}"))
            if not found:
                for i in dead:
                    q = Point(nxy[i])
                    if ring.distance(q) <= 6.0 or poly.contains(q):
                        w = ring.interpolate(ring.project(q))
                        found.append((tuple(map(float, proj.inv(w.x, w.y))), f"마법 지도 그래프 막다른 끝(노드 {i})"))
            if not found:
                for q, oid in run_ends:
                    if ring.distance(q) <= 3.0:
                        w = ring.interpolate(ring.project(q))
                        found.append((tuple(map(float, proj.inv(w.x, w.y))), f"OSM way {oid} 끝"))
            if not found:
                k = all_tree.nearest(poly)
                near = all_lines[int(k)]
                from shapely.ops import nearest_points
                w, _ = nearest_points(ring, near)
                found.append((tuple(map(float, proj.inv(w.x, w.y))), "추정: 가장 가까운 길 쪽 벽"))
        seen = set()
        for (lon, lat), src in found:
            key = (round(lon, 6), round(lat, 6))
            if key in seen:
                continue
            seen.add(key)
            entrances_out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
                                  "properties": {"type": "entrance", "building": b, "source": src}})

    feats = []
    for line, hw, oid, name in kept:
        kind, cf = KIND[hw]
        ll = to_ll(line)
        feats.append({"type": "Feature", "geometry": {"type": "LineString",
                                                      "coordinates": [[round(x, 7), round(y, 7)] for x, y in ll.coords]},
                      "properties": {"type": "path", "kind": kind, "costFactor": cf, "highway": hw, "osm": oid,
                                     "name": name, "length_m": round(line.length, 1), "source": f"OSM way {oid}"}})
    return {"type": "FeatureCollection",
            "meta": {"source": SOURCE, "zone_m": zone, "gap_m": gap, "min_run_m": min_run,
                     "note": "type = path 는 graph_slopes.py 가 그래프에 더하고, type = entrance 는 slope_travel.py 가 출입구로 쓴다"},
            "features": feats + entrances_out}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=str(OUT))
    ap.add_argument("--zone", type=float, default=ZONE)
    ap.add_argument("--gap", type=float, default=GAP)
    args = ap.parse_args(argv)
    out = Path(args.output)
    manual = [p for p in sorted(PATCH_DIR.glob("*.geojson")) if p.resolve() != out.resolve()]
    fc = build(zone=args.zone, gap=args.gap, manual=manual)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fc, ensure_ascii=False, indent=1), encoding="utf-8")
    paths = [f for f in fc["features"] if f["properties"]["type"] == "path" and f["properties"].get("role") != "entrance_link"]
    ents = [f for f in fc["features"] if f["properties"]["type"] == "entrance"]
    by = defaultdict(list)
    for f in ents:
        by[f["properties"]["source"].split("(")[0].split(" ")[0]].append(f["properties"]["building"])
    print(f"저장: {out}")
    print(f"  길 {len(paths)}개, {sum(f['properties']['length_m'] for f in paths):.0f} m (OSM, 그래프에서 {args.gap:g} m 넘게 떨어진 조각)")
    print(f"  출입구 {len(ents)}개: " + ", ".join(f"{k} {len(v)}" for k, v in by.items())
          + " (접속선은 scripts/entrance_links.py 가 links.geojson 에 만든다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
