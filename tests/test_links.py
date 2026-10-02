"""출입구 접속선(scripts/entrance_links.py → data/graph_patch/links.geojson)과 그걸 쓰는 그래프·경로 테스트."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "scripts"))

be = pytest.importorskip("building_elevation")
import slope_travel as st  # noqa: E402

# rasterio 의 from_origin 이 내는 예고 경고(행렬 곱 연산자). 우리 코드와 상관없다(test_elevation.py 와 같이 가린다)
pytestmark = pytest.mark.filterwarnings("ignore:Use `@` matmul:PendingDeprecationWarning")

PROJ = be.LocalProj()


def _ll(x, y):
    a, b = PROJ.inv(x, y)
    return [float(np.ravel(a)[0]), float(np.ravel(b)[0])]


def _graph(pts, links):
    lon, lat = PROJ.inv([p[0] for p in pts.values()], [p[1] for p in pts.values()])
    nodes = [{"id": i, "lng": float(a), "lat": float(b), "ele": 100.0} for i, a, b in zip(pts, lon, lat)]
    edges, k = [], 0
    for a, b in links:
        d = float(np.hypot(*(np.subtract(pts[b], pts[a]))))
        for u, v in ((a, b), (b, a)):
            k += 1
            edges.append({"id": k, "from": u, "to": v, "distance": d, "kind": "footway", "walkable": True,
                          "costFactor": 1, "isTunnel": False})
    return {"nodes": nodes, "edges": edges}


def _link(door, end, building="D"):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [_ll(*door), _ll(*end)]},
            "properties": {"type": "path", "role": "entrance_link", "building": building, "kind": "footway",
                           "costFactor": 1, "snap": 0.5, "link": 1.0}}


def test_shared_door_node():
    """한 출입구에서 나가는 접속선 여럿은 출입구 노드 하나를 같이 쓰고, 경로는 그 노드에서 더 가까운 쪽으로 나간다."""
    gp = pytest.importorskip("graph_patch")
    # 남북 길 1–2 (x = 0)와 동서 길 3–4 (y = 60). 출입구 (20, 40)에서 두 길로 접속선
    g = _graph({1: (0, 0), 2: (0, 100), 3: (-50, 60), 4: (100, 60), 5: (0, 60)}, [(1, 5), (5, 2), (3, 5), (5, 4)])
    gp.apply_patch(g, [_link((20, 40), (0, 40)), _link((20, 40), (20, 60))])
    doors = [n for n in g["nodes"] if n.get("entrance")]
    assert len(doors) == 1
    door = doors[0]["id"]
    out = [e for e in g["edges"] if e["from"] == door]
    assert len(out) == 2 and sorted(round(e["distance"]) for e in out) == [20, 20]
    r = st.Router(g, PROJ)
    att = r.attach(*_ll(20, 40))
    assert set(att) == {r.ids.index(door)} and r.is_door(*_ll(20, 40))
    res = r.routes({"D": [tuple(_ll(20, 40))], "N": [tuple(_ll(100, 60))]})
    s, _, geom = res[("D", "N")]
    assert float(s[-1]) == pytest.approx(20 + 80, abs=0.05)  # 북쪽 접속선 → 동서 길 동쪽 끝


def test_router_uses_linked_entrances_only():
    """접속선(출입구 노드)이 있는 출입구가 하나라도 있으면 그 건물은 접속선 없는 출입구를 쓰지 않는다(직선이 벽을 뚫을 수 있다).
    출입구 노드가 하나도 없는 지점만 예전처럼 가장 가까운 길에 직선으로 잇는다(router.fallback)."""
    gp = pytest.importorskip("graph_patch")
    g = _graph({1: (0, 0), 2: (0, 200), 3: (30, 0), 4: (30, 200)}, [(1, 2), (3, 4), (1, 3)])
    gp.apply_patch(g, [_link((10, 150), (0, 150))])  # 출입구 (10, 150) → 서쪽 길
    r = st.Router(g, PROJ)
    pts = {"D": [tuple(_ll(10, 150)), tuple(_ll(25, 150))],  # 두 번째 출입구는 접속선 없음(동쪽 길 5 m 옆)
           "N": [tuple(_ll(30, 200))]}
    res = r.routes(pts)
    s, _, geom = res[("D", "N")]
    assert r.fallback == ["N"]
    assert float(s[-1]) == pytest.approx(10 + 150 + 30 + 200, abs=0.05)  # 서쪽 출입구로만: 접속 10 + 아래로 150 + 30 + 위로 200


def test_link_search_goes_around_wall():
    """격자 탐색: 출입구와 길 사이 벽이 있으면 벽 끝을 돌아가고, 줄 당기기한 선도 벽을 지나지 않는다."""
    el = pytest.importorskip("entrance_links")
    pytest.importorskip("rasterio")
    pytest.importorskip("shapely")
    from shapely.geometry import LineString

    grid = el.Grid((-10.0, -10.0, 40.0, 50.0))
    wall = LineString([(10, -10), (10, 30)])
    road = LineString([(20, -10), (20, 50)])
    block = grid.burn([(wall.buffer(el.WALL_HALF, cap_style="flat"), 2)])
    target = grid.burn([(road.buffer(0.3), 1)], dtype="int32", all_touched=True)
    start = grid.rc(5.0, 10.0)
    found, prev = el.search(block, target, start, 200, 10, set())
    assert found
    d, cell, _ = min(found)
    cells = [cell]
    while cells[-1] in prev:
        cells.append(prev[cells[-1]])
    cells.reverse()
    pts = [(5.0, 10.0)] + [grid.xy(*c) for c in cells[1:]]
    line = LineString(el.pull(grid, block, pts, set()))
    assert not line.intersects(wall)
    assert line.length > 28 and max(y for _, y in line.coords) >= 29.5  # 벽 끝(y = 30)까지 올라가 돈다(직선이면 15 m)
    assert len(line.coords) >= 3


LINKS = DATA / "graph_patch" / "links.geojson"


@pytest.mark.skipif(not LINKS.exists(), reason="links.geojson 없음")
def test_links_file():
    """links.geojson: 접속선을 만들 출입구(손으로 그린 접속선이 있는 것은 빼고)마다 접속선이 있거나, 못 이은 출입구로 적혀 있다.
    접속선 첫 점이 출입구다. 못 이은 출입구는 몇 곳뿐이고, 그 동에는 접속선이 있는 다른 출입구가 있다."""
    el = pytest.importorskip("entrance_links")
    fc = json.loads(LINKS.read_text(encoding="utf-8"))
    feats = fc["features"]
    links = [f for f in feats if f["properties"].get("role") == "entrance_link"]
    unlinked = [f for f in feats if f["properties"]["type"] == "entrance_unlinked"]
    assert links and len(unlinked) <= 5
    assert fc["meta"]["stats"]["unlinked"] == len(unlinked) and fc["meta"]["stats"]["links"] == len(links)
    key = lambda lon, lat: (round(float(lon), 6), round(float(lat), 6))  # noqa: E731
    starts = {key(*f["geometry"]["coordinates"][0][:2]) for f in links}
    missing = {key(*f["geometry"]["coordinates"][:2]) for f in unlinked}
    for f in links:
        p = f["properties"]
        assert p["kind"] in ("footway", "steps") and p["snap"] <= 1 and p["link"] <= 1 and p["length_m"] < 100
        assert p["entrances"] and all("#" in e for e in p["entrances"])
    others = [q for q in sorted((DATA / "graph_patch").glob("*.geojson")) if q.name != LINKS.name]
    ents, skipped = el.entrance_list(DATA / "building_entrances.csv", others)
    assert len(ents) > 300
    for e in ents:
        assert key(e["lon"], e["lat"]) in starts | missing, e
    hand = [f for q in others for f in json.loads(q.read_text(encoding="utf-8"))["features"]
            if f["properties"].get("role") == "entrance_link"]
    assert len(skipped["curated"]) >= len({key(*f["geometry"]["coordinates"][0][:2]) for f in hand}) > 0
    linked = {e.split("#")[0] for f in links + hand for e in f["properties"].get("entrances") or [f["properties"]["building"]]}
    for f in unlinked:  # 못 이은 출입구가 있는 동도 다른 출입구로 드나든다
        assert f["properties"]["building"] in linked, f["properties"]


@pytest.mark.skipif(not LINKS.exists(), reason="links.geojson 없음")
def test_links_avoid_buildings():
    """접속선은 1:1,000 수치지형도 건물(무벽건물 제외)을 출입구 둘레 말고는 지나지 않는다."""
    el = pytest.importorskip("entrance_links")
    pytest.importorskip("shapely")
    pytest.importorskip("shapefile")
    pytest.importorskip("pyproj")
    from shapely.geometry import LineString, Point, shape
    from shapely.ops import transform
    from shapely.strtree import STRtree

    solid = [g for g, a in el.read_layer(el.sheet_dirs(), el.BUILDING, PROJ) if a.get("종류") != "무벽건물"]
    if not solid:
        pytest.skip("수치지형도 건물 없음")
    tree = STRtree(solid)
    to_m = lambda g: transform(lambda x, y, z=None: PROJ.fwd(x, y), g)  # noqa: E731
    for f in json.loads(LINKS.read_text(encoding="utf-8"))["features"]:
        if f["properties"].get("role") != "entrance_link":
            continue
        line = to_m(shape(f["geometry"]))
        door = Point(line.coords[0])
        depth = f["properties"].get("door_depth_m", 0.0)
        free = max(depth + 1.5, f["properties"].get("door_clear_m", 0.0) + 0.5)  # 처마·필로티 밑 출입구 둘레(clear)는 지나갈 수 있다
        for i in tree.query(line):
            # 격자가 0.5 m 라 벽 선에서 한 칸(대각 0.7 m) 안쪽까지는 스칠 수 있다. 그보다 깊이 건물 안을 지나면 안 된다
            part = line.intersection(solid[int(i)].buffer(-0.75)).difference(door.buffer(free))
            assert part.length < 0.5, (f["properties"]["entrances"], part.length)


def test_block_edges():
    """type = block: 받은 엣지에 blocked 를 달고(값은 그대로), 경로·패치 잇기가 그 엣지를 쓰지 않는다."""
    gp = pytest.importorskip("graph_patch")
    g = _graph({1: (0, 0), 2: (0, 100), 3: (50, 0), 4: (50, 100)}, [(1, 2), (1, 3), (3, 4), (2, 4)])
    block = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [_ll(0, 0), _ll(0, 100)]},
             "properties": {"type": "block", "edges": [[2, 1]], "note": "건물을 뚫는 선"}}
    gp.apply_patch(g, [block, _link((-5, 50), (0, 50))])
    blocked = [e for e in g["edges"] if e.get("blocked")]
    assert len(blocked) == 2 and all(e["walkable"] and e["blocked"] == "건물을 뚫는 선" for e in blocked)
    # 접속선은 막은 엣지 1–2 에 붙지 않고(1 m 안에 다른 엣지가 없으니) 제 끝에 새 노드만 생긴다 → 본체와 떨어진다
    door = next(n["id"] for n in g["nodes"] if n.get("entrance"))
    assert all(e["to"] not in (1, 2) for e in g["edges"] if e["from"] == door)
    r = st.Router(g, PROJ)
    res = r.routes({"A": [tuple(_ll(0, 0))], "B": [tuple(_ll(0, 100))]})
    s, _, _ = res[("A", "B")]
    assert float(s[-1]) == pytest.approx(50 + 100 + 50, abs=0.05)  # 1→3→4→2 로 돈다


def _path(coords, **props):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [_ll(*c) for c in coords]},
            "properties": {"type": "path", "kind": "footway", "costFactor": 1, "snap": 0.5, "link": 1.0, **props}}


def _block(pairs, note="없는 길"):
    return {"type": "Feature", "geometry": None, "properties": {"type": "block", "edges": pairs, "note": note}}


def _neighbors(g):
    adj = {}
    for e in g["edges"]:
        if not e.get("blocked"):
            adj.setdefault(e["from"], set()).add(e["to"])
    return adj


def _at(g, x, y, tol=0.05):
    """(x, y) 자리의 노드 번호들."""
    out = []
    for n in g["nodes"]:
        px, py = np.ravel(PROJ.fwd(n["lng"], n["lat"]))
        if math.hypot(px - x, py - y) <= tol:
            out.append(n["id"])
    return out


def test_heal_junctions():
    """받은 그래프에서 엣지 '위'에 찍혀 있는데 이어져 있지 않은 노드를 잇는다(조각 엣지 role = junction, split_of = 원래 엣지).
    받은 노드·엣지는 그대로. 엣지 끝 0.5 m 안의 노드, 0.3 m 넘게 벗어난 노드는 잇지 않는다."""
    gp = pytest.importorskip("graph_patch")
    # 길 1–2 (x = 0) 위 (0, 40)에 노드 3 이 찍혀 있고 거기서 동쪽으로 3–4. 5 는 끝에서 0.2 m, 7 은 0.4 m 옆
    g = _graph({1: (0, 0), 2: (0, 100), 3: (0, 40), 4: (30, 40), 5: (0, 99.8), 6: (30, 99.8), 7: (0.4, 60), 8: (30, 60)},
               [(1, 2), (3, 4), (5, 6), (7, 8)])
    before = json.loads(json.dumps(g))
    gp.apply_patch(g, [])
    assert g["nodes"] == before["nodes"] and g["edges"][:8] == before["edges"]
    added = g["edges"][8:]
    assert {(e["from"], e["to"]) for e in added} == {(1, 3), (3, 1), (3, 2), (2, 3)}
    assert all(e["role"] == "junction" and e["split_of"] == 1 and e["src"] == "ttwizard" for e in added)
    assert sorted({round(e["distance"]) for e in added}) == [40, 60]
    r = st.Router(g, PROJ)
    res = r.routes({"A": [tuple(_ll(0, 0))], "B": [tuple(_ll(30, 40))]})
    assert float(res[("A", "B")][0][-1]) == pytest.approx(40 + 30, abs=0.05)
    assert "patch" in g["meta"]


def test_heal_uses_pieces_of_split_edge():
    """받은 그래프가 엣지 위 노드를 양 끝과 따로 이어 둔 곳(원래 엣지 1–2 + 조각 1–5, 5–2): 새 조각은 더하지 않지만,
    패치 길·접속선은 원래 엣지가 아니라 조각에 붙는다(원래 엣지에 붙으면 그 자리에서 5 로 바로 못 간다)."""
    gp = pytest.importorskip("graph_patch")
    g = _graph({1: (0, 0), 2: (0, 100), 5: (0, 50)}, [(1, 2), (1, 5), (5, 2)])
    gp.apply_patch(g, [_link((5, 30), (0, 30))])
    assert not [e for e in g["edges"] if e.get("role") == "junction" and e.get("split_of") == 1 and {e["from"], e["to"]} <= {1, 2, 5}]
    (foot,) = _at(g, 0, 30)
    door = next(n["id"] for n in g["nodes"] if n.get("entrance"))
    assert _neighbors(g)[foot] == {1, 5, door}


def test_block_junction_pieces():
    """끊긴 갈림목을 이은 조각과 맞물린 막기: 조각 [3, 2] 를 막으면 원래 엣지 1–2 도 막히고 다른 조각 1–3 은 남는다.
    원래 엣지 [1, 2] 를 막으면 그 위의 노드를 잇지 않는다."""
    gp = pytest.importorskip("graph_patch")
    pts = {1: (0, 0), 2: (0, 100), 3: (0, 40), 4: (30, 40), 5: (60, 0), 6: (60, 100)}
    links = [(1, 2), (3, 4), (1, 5), (5, 6), (6, 2)]
    blocked = lambda g: {(min(e["from"], e["to"]), max(e["from"], e["to"])) for e in g["edges"] if e.get("blocked")}  # noqa: E731
    g = _graph(pts, links)
    gp.apply_patch(g, [_block([[3, 2]])])
    assert blocked(g) == {(2, 3), (1, 2)}
    r = st.Router(g, PROJ)
    res = r.routes({"A": [tuple(_ll(0, 0))], "B": [tuple(_ll(0, 100))], "C": [tuple(_ll(30, 40))]})
    assert float(res[("A", "B")][0][-1]) == pytest.approx(60 + 100 + 60, abs=0.05)  # 1→5→6→2 로 돈다
    assert float(res[("A", "C")][0][-1]) == pytest.approx(40 + 30, abs=0.05)        # 남은 조각 1–3 으로
    g = _graph(pts, links)
    gp.apply_patch(g, [_block([[1, 2]])])  # 막은 엣지 위의 노드는 잇지 않는다(조각을 만들지 않는다)
    assert blocked(g) == {(1, 2)} and not [e for e in g["edges"] if e.get("role") == "junction"]
    assert _neighbors(g)[3] == {4}


def test_no_shortcut_through_doors():
    """다른 건물의 출입구 노드는 지나가지 않는다: 한 출입구에서 나가는 접속선 둘이 길과 길 사이 지름길이 되지 않는다.
    그 건물을 드나드는 경로는 접속선을 쓴다."""
    gp = pytest.importorskip("graph_patch")
    # 나란한 두 길 1–2 (x = 0), 3–4 (x = 40)가 남쪽(1–3)에서만 이어져 있고, 그 사이 건물 D 의 문 (20, 80)에서 두 길로 접속선
    g = _graph({1: (0, 0), 2: (0, 100), 3: (40, 0), 4: (40, 100)}, [(1, 2), (3, 4), (1, 3)])
    gp.apply_patch(g, [_link((20, 80), (0, 80)), _link((20, 80), (40, 80))])
    pts = {"X": [tuple(_ll(0, 100))], "Y": [tuple(_ll(40, 100))], "D": [tuple(_ll(20, 80))]}
    r = st.Router(g, PROJ)
    res = r.routes(pts)
    assert float(res[("X", "Y")][0][-1]) == pytest.approx(100 + 40 + 100, abs=0.05)  # 문을 지나면 80 m
    assert float(res[("X", "D")][0][-1]) == pytest.approx(20 + 20, abs=0.05)
    assert float(res[("Y", "D")][0][-1]) == pytest.approx(20 + 20, abs=0.05)
    assert r.fallback == ["X", "Y"]
    door = next(k for k, n in enumerate(g["nodes"]) if n.get("entrance"))
    _, path, _, _ = r.paths(pts)[("X", "Y")]
    assert door not in path
    loose = st.Router(g, PROJ, through_doors=True)  # 비교용: 문을 지나가게 두면 지름길이 생긴다
    assert float(loose.routes(pts)[("X", "Y")][0][-1]) == pytest.approx(20 + 20 + 20 + 20, abs=0.05)


def test_buildings_sharing_a_door():
    """두 지점이 같은 출입구를 쓰면(207동·52-2동처럼) 그 사이는 0 m 이고, 다른 지점과는 같은 경로다."""
    gp = pytest.importorskip("graph_patch")
    g = _graph({1: (0, 0), 2: (0, 100)}, [(1, 2)])
    gp.apply_patch(g, [_link((20, 80), (0, 80))])
    pts = {"P": [tuple(_ll(20, 80))], "Q": [tuple(_ll(20, 80))], "N": [tuple(_ll(0, 0))]}
    res = st.Router(g, PROJ).routes(pts)
    assert float(res[("P", "Q")][0][-1]) == pytest.approx(0, abs=0.01)
    assert float(res[("P", "N")][0][-1]) == pytest.approx(100, abs=0.05) == float(res[("Q", "N")][0][-1])


def test_vertex_merge_and_late_ends():
    """길의 중간 꼭짓점이 이미 있는 노드와 0.3 m 안이면 그 노드를 쓴다(먼저 더한 길의 끝과 이어진다).
    붙일 곳이 없던 길 끝은 길을 다 더한 뒤 다시 붙인다(뒤에 읽은 패치 파일의 길 위에 놓인 끝)."""
    gp = pytest.importorskip("graph_patch")
    g = _graph({1: (0, 0), 2: (100, 0)}, [(1, 2)])
    a = _path([(20, 0), (20, 50)])                     # 끝 (20, 50)은 붙을 곳이 없다
    b = _path([(80, 0), (80, 50), (20, 50.1), (0, 50)])  # 중간 꼭짓점이 a 의 끝에서 0.1 m
    gp.apply_patch(g, [a, b])
    (end,) = _at(g, 20, 50, tol=0.2)                   # 노드 하나를 같이 쓴다
    adj = _neighbors(g)
    assert adj[end] == set(_at(g, 20, 0) + _at(g, 80, 50) + _at(g, 0, 50)) and len(adj[end]) == 3
    # 길 c 의 끝 (50, 30)이 나중에 더한 길 d 의 변 위에 있다 → 다 더한 뒤 그 변을 나눠 붙는다
    for order in ("cd", "dc"):
        g = _graph({1: (0, 0), 2: (100, 0)}, [(1, 2)])
        c = _path([(50, 0), (50, 30)])
        d = _path([(100, 0), (100, 30), (0, 30)])
        gp.apply_patch(g, [c, d] if order == "cd" else [d, c])
        (end,) = _at(g, 50, 30)
        assert _neighbors(g)[end] == set(_at(g, 50, 0) + _at(g, 100, 30) + _at(g, 0, 30)), order
        res = st.Router(g, PROJ).routes({"A": [tuple(_ll(0, 0))], "B": [tuple(_ll(0, 30))]})
        assert float(res[("A", "B")][0][-1]) == pytest.approx(50 + 30 + 50, abs=0.05), order


def test_door_is_not_a_path_vertex():
    """다른 접속선의 꼭짓점이 출입구 노드와 같은 자리여도 그 노드에 합치지 않는다(출입구는 지나가는 길이 아니다)."""
    gp = pytest.importorskip("graph_patch")
    g = _graph({1: (0, 0), 2: (0, 100)}, [(1, 2)])
    first = _link((10, 20), (0, 20), "A")
    second = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [_ll(20, 20), _ll(10, 20.1), _ll(0, 40)]},
              "properties": {"type": "path", "role": "entrance_link", "building": "B", "snap": 0.5, "link": 1.0}}
    gp.apply_patch(g, [first, second])
    doors = {n["building"]: n["id"] for n in g["nodes"] if n.get("entrance")}
    adj = _neighbors(g)
    assert adj[doors["A"]] == set(_at(g, 0, 20)) and len(_at(g, 10, 20, tol=0.2)) == 2


def test_paths_do_not_attach_to_tunnels():
    """터널·다리 엣지(isTunnel) 가운데에는 길·접속선을 붙이지 않는다(땅 위 길이 지하 통로와 이어지지 않게). 끝 노드에는 붙는다."""
    gp = pytest.importorskip("graph_patch")
    g = _graph({1: (0, 0), 2: (100, 0), 3: (0, 10), 4: (100, 10)}, [(1, 2), (3, 4), (1, 3)])
    for e in g["edges"]:
        if {e["from"], e["to"]} == {1, 2}:
            e["isTunnel"] = True
    gp.apply_patch(g, [_link((50, 4), (50, 0.2), "A"), _link((0, -5), (0, 0), "B")])
    doors = {n["building"]: n["id"] for n in g["nodes"] if n.get("entrance")}
    adj = _neighbors(g)
    (end,) = adj[doors["A"]]
    assert adj[end] == {doors["A"]}                 # 터널 위 0.2 m 에 놓인 끝: 붙지 않는다
    assert not [e for e in g["edges"] if e.get("split_of")]
    assert adj[doors["B"]] == {1}                   # 터널 끝 노드에는 붙는다


def test_entrance_list_priority(tmp_path):
    """접속선을 만들 출입구: replace = true 출입구가 있는 동은 그것만(번호 no, 없으면 r1 …, 접속선 조건도 같이),
    없으면 building_entrances.csv, 그것도 없으면 패치의 자동 출입구(p1 …). 손으로 그린 접속선이 나가는 출입구는 건너뛴다."""
    el = pytest.importorskip("entrance_links")
    a1, a2, b0, b1, b2, c1 = (_ll(x, 0) for x in (0, 10, 20, 30, 40, 50))
    with open(tmp_path / "ent.csv", "w", encoding="utf-8") as f:
        f.write("building,entrance_no,lat,lon\n")
        for b, no, (lon, lat) in (("A", "1", a1), ("A", "2", a2), ("B", "1", b0)):
            f.write(f"{b},{no},{lat},{lon}\n")
    ent = lambda b, ll, **p: {"type": "Feature", "geometry": {"type": "Point", "coordinates": ll},  # noqa: E731
                              "properties": {"type": "entrance", "building": b, **p}}
    hand = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [a2, _ll(10, 5)]},
            "properties": {"type": "path", "role": "entrance_link", "building": "A"}}
    feats = [ent("B", b1, replace=True, no="a1", max_links=2, clear=9), ent("B", b2, replace=True),
             ent("C", c1), ent("A", _ll(5, 5)), hand]
    patch = tmp_path / "p.geojson"
    patch.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    ents, skipped = el.entrance_list(tmp_path / "ent.csv", [patch])
    got = {(e["building"], e["no"]): e for e in ents}
    assert set(got) == {("A", "1"), ("B", "a1"), ("B", "r2"), ("C", "p1")}
    assert got[("B", "a1")]["max_links"] == 2 and got[("B", "a1")]["clear"] == 9 and "max_links" not in got[("B", "r2")]
    assert (got[("B", "a1")]["lon"], got[("B", "a1")]["lat"]) == tuple(b1)
    assert skipped == {"reported": ["B"], "curated": ["A#2"]}


def _write_building(folder, ring_m):
    """1:1,000 도엽 폴더에 건물 한 채(N1A_B0010000). ring_m = 로컬 m 꼭짓점(시계 방향)."""
    shapefile = pytest.importorskip("shapefile")
    pyproj = pytest.importorskip("pyproj")
    tr = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)
    ring = [list(tr.transform(*_ll(x, y))) for x, y in ring_m]
    folder.mkdir(parents=True)
    w = shapefile.Writer(str(folder / "N1A_B0010000"), shapeType=shapefile.POLYGON, encoding="cp949")
    w.field("종류", "C", 20)
    w.field("주기", "C", 40)
    w.poly([ring + ring[:1]])
    w.record("주택외건물", "시험동")
    w.close()


def test_build_links_barrier_and_clear(tmp_path):
    """접속선 만들기: 패치의 type = barrier 선은 넘지 않고 돌아간다. 건물 윤곽 깊이 안쪽의 문(필로티 밑)은 clear 를 주면
    그 반경 안의 건물 칸을 지나 가까운 쪽으로 나간다(안 주면 가장 가까운 벽으로만 나가 돌아간다)."""
    el = pytest.importorskip("entrance_links")
    for mod in ("rasterio", "shapely", "scipy"):
        pytest.importorskip(mod)
    from shapely.geometry import LineString
    from shapely.ops import transform

    # 서쪽 길 1–2 (x = 0), 북쪽 길 5–6 (y = 30, x 170~250), 둘을 잇는 2–5. 건물 (200~220, 0~20)
    g = _graph({1: (0, -50), 2: (0, 50), 5: (170, 30), 6: (250, 30)}, [(1, 2), (2, 5), (5, 6)])
    (tmp_path / "graph.json").write_text(json.dumps(g), encoding="utf-8")
    _write_building(tmp_path / "topo" / "(B010)수치지도_376120581_2025_test", [(200, 0), (200, 20), (220, 20), (220, 0)])
    lon, lat = _ll(10, 0)
    (tmp_path / "ent.csv").write_text(f"building,entrance_no,lat,lon\nW,1,{lat},{lon}\n", encoding="utf-8")
    barrier = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [_ll(5, -20), _ll(5, 20)]},
               "properties": {"type": "barrier", "id": "fence", "source": "test"}}

    def run(name, clear=None, with_barrier=True):
        door = {"type": "Feature", "geometry": {"type": "Point", "coordinates": _ll(210, 6)},
                "properties": {"type": "entrance", "building": "P", "replace": True, "no": "1", **({"clear": clear} if clear else {})}}
        patch = tmp_path / f"{name}.geojson"
        patch.write_text(json.dumps({"type": "FeatureCollection", "features": [door] + ([barrier] if with_barrier else [])}),
                         encoding="utf-8")
        fc = el.build(graph_path=tmp_path / "graph.json", entrances=tmp_path / "ent.csv", topo=tmp_path / "topo", dem_dir=None,
                      patch_files=[patch], out_path=tmp_path / "links.geojson")
        to_m = lambda geom: transform(lambda x, y, z=None: PROJ.fwd(x, y), geom)  # noqa: E731
        out = {}
        for f in fc["features"]:
            assert f["properties"]["type"] == "path", f["properties"]
            out.setdefault(f["properties"]["entrances"][0], []).append(to_m(LineString(f["geometry"]["coordinates"])))
        return out, fc

    plain, _ = run("plain", with_barrier=False)
    assert min(l.length for l in plain["W#1"]) == pytest.approx(10, abs=0.3)  # 장애물이 없으면 서쪽 길까지 곧게
    fenced, fc = run("fenced")
    fence = LineString([(5, -19.5), (5, 19.5)])
    assert fc["meta"]["stats"]["patch_barriers"] == 1
    assert not any(l.intersects(fence) for l in fenced["W#1"])
    assert min(l.length for l in fenced["W#1"]) == pytest.approx(math.hypot(5, 20.5) + 5, abs=1.5)  # 울타리 끝을 돌아간다
    # 문 (210, 6): 남쪽 벽까지 6 m, 북쪽 벽까지 14 m. 길은 북쪽에만 있다
    # 남쪽 벽으로 나가 건물을 돌아간다(동쪽·서쪽으로 돌거나 서쪽 길로). 곧게 나가 돌면 47 m, 벽까지 비스듬히 가면 43 m
    assert all(min(y for _, y in l.coords) < 0.5 for l in fenced["P#1"])
    assert 40 < min(l.length for l in fenced["P#1"]) < 47.5
    opened, fc = run("clear", clear=15)
    assert min(l.length for l in opened["P#1"]) == pytest.approx(24, abs=0.5)  # 건물 밑(필로티)을 지나 북쪽으로 곧게
    assert {f["properties"].get("door_clear_m") for f in fc["features"] if f["properties"]["entrances"] == ["P#1"]} == {15}


SLOPE = DATA / "magicmap" / "roads_graph_slope.json"


@pytest.mark.skipif(not (SLOPE.exists() and LINKS.exists()), reason="경사 그래프 없음")
def test_real_routes_do_not_pass_doors():
    """실제 그래프: 경로의 중간 노드에 출입구 노드가 없다(양 끝만). 접속선이 없어 직선으로 잇는 지점은 공사 중인 73동뿐."""
    graph = json.loads(SLOPE.read_text(encoding="utf-8"))
    ids = ["1", "3", "26", "30", "43-1", "59", "73", "83", "101", "220", "301", "500", "900", "919", "GATE"]
    pts = st.load_points(ids, extra=DATA / "dorm_buildings.csv", patch=[DATA / "graph_patch"])
    assert set(pts) == set(ids)
    r = st.Router(graph, PROJ)
    paths = r.paths(pts)
    assert len(paths) == len(ids) * (len(ids) - 1) // 2 and r.fallback == ["73"]
    doors = set(r.door_ids)
    assert len(doors) > 300
    for (a, b), (_, path, _, total) in paths.items():
        assert not doors & set(path[1:-1]), (a, b)
        assert 0 < total < 3000, (a, b)
        if a != "73" and b != "73":
            assert path[0] in doors and path[-1] in doors, (a, b)
