"""도로 그래프 경사(graph_slopes.py), 건물쌍 거리표 변환(magicmap_travel.py), 경사 반영 이동시간(slope_travel.py) 테스트.
DEM은 가짜 함수로 대신하거나 쓰지 않는다."""

import base64
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

be = pytest.importorskip("building_elevation")
gs = pytest.importorskip("graph_slopes")
import magicmap_travel as mt  # noqa: E402
import slope_travel as st  # noqa: E402
import campus_model as cm  # noqa: E402
from ttwizard.travel import TravelMatrix  # noqa: E402

PROJ = be.LocalProj()


class FakeDem:
    """z = 100 + 0.1·북(m) + 0.02·동(m). (0, 150) 근처에 30 m 봉우리(터널 위), (100, 20) 근처에 10 m 골짜기(다리 밑).
    동쪽 1 km 밖은 DEM 범위 밖(NaN)."""

    def sample(self, lons, lats):
        x, y = PROJ.fwd(np.atleast_1d(lons), np.atleast_1d(lats))
        z = 100 + 0.1 * y + 0.02 * x
        z = z + 30.0 * (np.hypot(x, y - 150) < 10)
        z = z - 10.0 * ((np.abs(x - 100) < 1) & (np.abs(y - 20) < 10))
        z = np.asarray(z, float)
        z[x > 1000] = np.nan
        return z


def _graph():
    pts = {1: (0, 0), 2: (0, 50), 3: (0, 100), 4: (50, 100), 5: (0, 150), 6: (0, 200), 7: (0, 250),
           8: (100, 0), 9: (100, 40), 10: (2000, 40), 11: (100, -50)}
    lon, lat = PROJ.inv([p[0] for p in pts.values()], [p[1] for p in pts.values()])
    nodes = [{"id": i, "lng": float(a), "lat": float(b)} for i, a, b in zip(pts, lon, lat)]
    links = [(1, 2, False), (2, 3, False), (3, 4, False), (3, 5, True), (5, 6, True), (6, 7, False),
             (8, 9, False), (9, 10, False), (11, 8, False)]
    edges, k = [], 0
    for a, b, tunnel in links:
        d = float(np.hypot(*(np.subtract(pts[b], pts[a]))))
        for u, v in ((a, b), (b, a)):
            k += 1
            edges.append({"id": k, "from": u, "to": v, "distance": d, "kind": "footway", "oneway": False,
                          "walkable": True, "costFactor": 1, "isTunnel": tunnel})
    return {"nodes": nodes, "edges": edges}


def _bridge_points():
    y = np.arange(0, 40.5, 1.0)
    return np.column_stack([np.full_like(y, 100.0), y])


def test_graph_slopes():
    g = _graph()
    ele, res, index = gs.compute(g, FakeDem(), PROJ, _bridge_points(), np.zeros((0, 2)))
    z = {i: ele[index[i]] for i in index}
    rec = lambda a, b: res[(min(index[a], index[b]), max(index[a], index[b]))]  # noqa: E731
    # 지면: 북쪽 50 m에 5 m → +10 %, 거꾸로 −10 %
    fwd = gs.directed(rec(1, 2), z[1], z[2], index[1] <= index[2])
    back = gs.directed(rec(1, 2), z[2], z[1], index[2] <= index[1])
    assert fwd["surface"] == "ground" and fwd["grade"] == pytest.approx(10, abs=0.05)
    assert fwd["ascent"] == pytest.approx(5, abs=0.05) and fwd["descent"] == pytest.approx(0, abs=0.05)
    assert back["grade"] == pytest.approx(-10, abs=0.05) and back["descent"] == pytest.approx(5, abs=0.05)
    assert fwd["maxGrade"] == pytest.approx(10, abs=0.1)
    assert gs.directed(rec(3, 4), z[3], z[4], True)["grade"] == pytest.approx(2, abs=0.05)  # 동쪽 2 %
    # 터널 안쪽 노드 5는 땅(봉우리 145 m)이 아니라 입구 3(110)과 6(120) 사이 선형 보간
    assert rec(3, 5)["surface"] == "tunnel" and z[5] == pytest.approx(115, abs=0.05)
    t = gs.directed(rec(3, 5), z[3], z[5], True)
    assert t["ascent"] == pytest.approx(5, abs=0.05) and t["maxGrade"] == pytest.approx(10, abs=0.05)
    # OSM 다리: 밑의 골짜기를 무시하고 양 끝만
    br = gs.directed(rec(8, 9), z[8], z[9], True)
    assert rec(8, 9)["surface"] == "bridge_osm"
    assert br["ascent"] == pytest.approx(4, abs=0.05) and br["descent"] == pytest.approx(0, abs=0.05)
    # DEM 범위 밖
    assert np.isnan(z[10]) and rec(9, 10)["surface"] == "no_dem"
    assert gs.directed(rec(9, 10), z[9], z[10], True) == {"surface": "no_dem"}


def test_max_grade_window():
    s = np.arange(0, 41, 2.0)
    zz = np.where(s < 20, 0.0, 5.0)  # 18~20 m 사이 5 m 계단
    assert gs._max_grade(s, zz, 10.0) == pytest.approx(50.0)  # 10 m 창에서 5 m
    assert gs._max_grade(np.array([0.0, 5.0]), np.array([0.0, 1.0]), 10.0) == pytest.approx(20.0)


def test_magicmap_travel(tmp_path):
    pairs = tmp_path / "pairs.csv"
    pairs.write_text("﻿from,to,distance_m,time_s\n1,2,66.0,60.0\n2,1,66.0,60.0\n1,301,1320.0,1200.0\n",
                     encoding="utf-8")
    travel = tmp_path / "travel.csv"
    travel.write_text("from,to,minutes,source\n1,2,3.5,measured\n1,301,99,tmap\n500,301,7,tmap\n", encoding="utf-8")
    assert mt.main(["--pairs", str(pairs), "-o", str(travel)]) == 0
    rows = {(r["from"], r["to"]): r for r in csv.DictReader(open(travel, encoding="utf-8"))}
    assert rows[("1", "2")]["minutes"] == "3.50" and rows[("1", "2")]["source"] == "measured"  # 실측 유지
    assert rows[("2", "1")]["minutes"] == "1.00" and rows[("1", "301")]["minutes"] == "20.00"
    assert rows[("1", "301")]["source"] == "magicmap"
    assert rows[("500", "301")]["source"] == "tmap"  # 표에 없는 쌍은 남긴다
    b = tmp_path / "b.csv"  # 알고리즘(TravelMatrix)이 그대로 읽는지
    b.write_text("building,name,lat,lon\n1,a,37.46,126.95\n2,b,37.46,126.951\n", encoding="utf-8")
    tm = TravelMatrix.load(b, travel)
    assert tm.minutes("2", "1") == 1.0 and tm.minutes("1", "2") == 3.5


def test_tobler_and_window():
    assert st.tobler(0.0) == pytest.approx(1.1)
    assert st.tobler(0.1) == pytest.approx(1.1 * math.exp(-0.35))  # 10 % 오르막
    assert st.tobler(-0.1) == pytest.approx(1.1)  # 10 % 내리막은 평지와 같은 속도
    assert st.tobler(-0.05) > st.tobler(0.0) > st.tobler(0.05)  # 완만한 내리막(−5 %)에서 가장 빠르다
    ds, g = st.window_grades(np.array([0.0, 100.0]), np.array([0.0, 10.0]), 30.0)
    assert ds.sum() == pytest.approx(100.0) and np.allclose(g, 0.1)
    # 몇 m 안에서 튀는 고도는 30 m 창에서 거의 사라진다
    s = np.array([0.0, 50.0, 52.0, 100.0])
    ds, g = st.window_grades(s, np.array([0.0, 0.0, 2.0, 2.0]), 30.0)
    assert np.abs(g).max() == pytest.approx(2.0 / 30.0, abs=1e-6)


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_slope_travel(tmp_path):
    # 북쪽으로 10 % 오르막인 200 m 길(노드 1~5)과 노드 3에서 동쪽으로 난 평지 40 m(노드 6)
    pts = {1: (0, 0), 2: (0, 50), 3: (0, 100), 4: (0, 150), 5: (0, 200), 6: (40, 100)}
    ele = {i: 100 + 0.1 * y for i, (_, y) in pts.items()}
    ele[6] = ele[3]
    lon, lat = PROJ.inv([p[0] for p in pts.values()], [p[1] for p in pts.values()])
    nodes = [{"id": i, "lng": float(a), "lat": float(b), "ele": ele[i]} for i, a, b in zip(pts, lon, lat)]
    edges, k = [], 0
    for a, b in [(1, 2), (2, 3), (3, 4), (4, 5), (3, 6)]:
        d = float(np.hypot(*(np.subtract(pts[b], pts[a]))))
        for u, v in ((a, b), (b, a)):
            k += 1
            edges.append({"id": k, "from": u, "to": v, "distance": d, "kind": "footway", "walkable": True,
                          "isTunnel": False, "surface": "ground"})
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"nodes": nodes, "edges": edges}), encoding="utf-8")

    def ll(x, y):
        a, b = PROJ.inv(x, y)
        return float(np.ravel(b)[0]), float(np.ravel(a)[0])

    _write_csv(tmp_path / "ent.csv", ["building", "lat", "lon"], [("A", *ll(0, 0)), ("B", *ll(0, 200))])
    _write_csv(tmp_path / "elev.csv", ["building", "lat", "lon"], [("C", *ll(45, 100))])  # 출입구 없음 → 건물 좌표
    magic = {("A", "B"): 200 / 1.1, ("A", "C"): 30.0, ("B", "C"): 150 / 1.1}  # A↔C 는 일부러 크게 다르게
    _write_csv(tmp_path / "pairs.csv", ["from", "to", "distance_m", "time_s"],
               [r for (a, b), t in magic.items() for r in ((a, b, t * 1.1, t), (b, a, t * 1.1, t))])
    out, stats, paths = tmp_path / "travel_slope.csv", tmp_path / "stats.csv", tmp_path / "paths.json"
    args = ["--graph", str(graph), "--pairs", str(tmp_path / "pairs.csv"), "--dem", str(tmp_path / "no_dem"),
            "--entrances", str(tmp_path / "ent.csv"), "--elevation", str(tmp_path / "elev.csv"),
            "--points", str(tmp_path / "none.csv"), "-o", str(out), "--stats", str(stats), "--paths", str(paths),
            "--extra", "", "--flat", "", "--patch"]
    assert st.main(args) == 0
    t = {(r["from"], r["to"]): float(r["minutes"]) for r in csv.DictReader(open(out, encoding="utf-8"))}
    rows = {(r["from"], r["to"]): r for r in csv.DictReader(open(stats, encoding="utf-8-sig"))}
    assert len(t) == 6
    # 10 % 오르막 200 m: 마법 지도 시간 × exp(0.35), 내리막 −10 %는 평지와 같다
    assert t[("A", "B")] == pytest.approx(200 / 1.1 / 60 * math.exp(0.35), rel=1e-3)
    assert t[("B", "A")] == pytest.approx(200 / 1.1 / 60, rel=1e-3)
    ab = rows[("A", "B")]
    assert float(ab["ascent_m"]) == pytest.approx(20, abs=0.1) and float(ab["net_rise_m"]) == pytest.approx(20, abs=0.1)
    assert float(ab["route_m"]) == pytest.approx(200, abs=1)
    # C: 노드 6 너머 5 m 떨어진 건물 좌표에서 평지로 접속 → A에서 100 m 오르막 + 40 m 평지 + 5 m
    ac = rows[("A", "C")]
    assert float(ac["route_m"]) == pytest.approx(145, abs=1)
    assert float(ac["slope_factor"]) > 1 > float(rows[("C", "A")]["slope_factor"]) - 0.05
    assert ac["check"] and not ab["check"]  # 마법 지도 표(0.5분)와 우리 경로(2.2분)가 크게 다르다
    # 웹 지도용 경로 모양: 곧은 길은 양 끝만, C 쪽은 노드 3에서 꺾인다
    shapes = json.loads(paths.read_text(encoding="utf-8"))
    assert shapes["ids"] == ["A", "B", "C"]
    line = st.decode_polyline(shapes["paths"]["A|B"])
    assert len(line) == 2 and line[0] == pytest.approx(ll(0, 0), abs=2e-5) and line[1] == pytest.approx(ll(0, 200), abs=2e-5)
    assert st.decode_polyline(shapes["paths"]["A|C"])[1] == pytest.approx(ll(0, 100), abs=2e-5)
    # 알고리즘(TravelMatrix)이 방향별로 읽는다
    b = tmp_path / "b.csv"
    _write_csv(b, ["building", "name", "lat", "lon"], [("A", "a", *ll(0, 0)), ("B", "b", *ll(0, 200))])
    tm = TravelMatrix.load(b, out)
    assert tm.minutes("A", "B") > tm.minutes("B", "A")


def test_campus_model(tmp_path):
    g = _graph()
    ele, res, index = gs.compute(g, FakeDem(), PROJ, _bridge_points(), np.zeros((0, 2)))
    for n, zz in zip(g["nodes"], ele):
        n["ele"] = None if np.isnan(zz) else float(zz)
    for e in g["edges"]:
        a, b = index[e["from"]], index[e["to"]]
        e["surface"] = res[(min(a, b), max(a, b))]["surface"]
    lon, lat = PROJ.inv(0.0, 50.0)
    blat, blon = float(np.ravel(lat)[0]), float(np.ravel(lon)[0])
    data = cm.build(g, FakeDem(), PROJ, {"A": ("가", blat, blon)}, step=10.0)
    nodes = np.frombuffer(base64.b64decode(data["nodes"]), "<u2").reshape(-1, 3)
    edges = np.frombuffer(base64.b64decode(data["edges"]), "<u2").reshape(-1, 2)
    codes = np.frombuffer(base64.b64decode(data["codes"]), "<u1")
    # 노드 10(DEM 밖)과 그 엣지는 빠진다
    assert data["counts"] == {"nodes": 10, "nodes_all": 11, "edges": 8, "tunnel": 2}
    assert len(nodes) == 10 and len(edges) == 8 and edges.max() < 10
    # 엣지 순서: 1-2, 2-3, 3-4(동쪽 2 %), 3-5·5-6(터널), 6-7, 8-9(다리), 8-11. 북쪽 길은 10 %(경계라 1 또는 2)
    assert codes[2] == 0 and codes[3] == 4 and codes[4] == 4
    assert set(codes[[0, 1, 5, 6, 7]].tolist()) <= {1, 2}
    ox, oy = data["origin"]
    assert nodes[0].tolist() == [round((0 - ox) * 10), round((0 - oy) * 10), 1000]  # 노드 1: (0, 0), 100 m
    t = data["terrain"]
    grid = np.frombuffer(base64.b64decode(t["z"]), "<u2")
    assert len(grid) == t["nx"] * t["ny"] and (grid != 65535).all()
    assert data["buildings"][0][:2] == ["A", "가"] and data["buildings"][0][4] == pytest.approx(105, abs=0.1)
    for name in ("campus_model_3d.html", "campus_model_2d.html"):
        page = cm.render(ROOT / "scripts" / name, data, "<script></script>")
        assert "__DATA__" not in page and "__LIBS__" not in page
        payload = page.split('<script type="application/json" id="data">', 1)[1].split("</script>", 1)[0]
        assert json.loads(payload)["counts"]["edges"] == 8


def test_slope_travel_extra_points(tmp_path):
    """표 밖 지점(기숙사 동): 우리 경로로 경사·평지 시간을 내고, 평지는 travel.csv 에 source = route 로. 출입구는 패치에서."""
    pts = {1: (0, 0), 2: (0, 50), 3: (0, 100), 4: (0, 150), 5: (0, 200), 6: (40, 100)}
    lon, lat = PROJ.inv([p[0] for p in pts.values()], [p[1] for p in pts.values()])
    nodes = [{"id": i, "lng": float(a), "lat": float(b), "ele": 100 + 0.1 * pts[i][1] if i != 6 else 110.0}
             for i, a, b in zip(pts, lon, lat)]
    edges, k = [], 0
    for a, b in [(1, 2), (2, 3), (3, 4), (4, 5), (3, 6)]:
        d = float(np.hypot(*(np.subtract(pts[b], pts[a]))))
        for u, v in ((a, b), (b, a)):
            k += 1
            edges.append({"id": k, "from": u, "to": v, "distance": d, "kind": "footway", "walkable": True,
                          "isTunnel": False, "surface": "ground"})
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"nodes": nodes, "edges": edges}), encoding="utf-8")

    def ll(x, y):
        a, b = PROJ.inv(x, y)
        return float(np.ravel(b)[0]), float(np.ravel(a)[0])

    _write_csv(tmp_path / "ent.csv", ["building", "lat", "lon"], [("A", *ll(0, 0)), ("B", *ll(0, 200))])
    _write_csv(tmp_path / "pairs.csv", ["from", "to", "distance_m", "time_s"],
               [("A", "B", 200, 200 / 1.1), ("B", "A", 200, 200 / 1.1)])
    # D 는 목록 좌표(노드 6 북쪽 15 m)가 있지만 패치 출입구(5 m)를 쓴다. E 는 목록 좌표만. F 는 지도 번호만(travel = N)
    _write_csv(tmp_path / "dorms.csv", ["building", "name", "lat", "lon", "travel"],
               [("D", "d", *ll(40, 115), "Y"), ("E", "e", *ll(0, 210), "Y"), ("F", "f", *ll(10, 10), "N")])
    patch = tmp_path / "patch"
    patch.mkdir()
    lon_d, lat_d = PROJ.inv(40.0, 105.0)
    (patch / "p.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(np.ravel(lon_d)[0]), float(np.ravel(lat_d)[0])]},
         "properties": {"type": "entrance", "building": "D", "source": "test"}}]}), encoding="utf-8")
    flat = tmp_path / "travel.csv"
    flat.write_text("from,to,minutes,source\nA,B,3.03,magicmap\nA,X,9.00,measured\nA,Z,5.00,route\n", encoding="utf-8")
    out, stats, paths = tmp_path / "travel_slope.csv", tmp_path / "stats.csv", tmp_path / "paths.json"
    args = ["--graph", str(graph), "--pairs", str(tmp_path / "pairs.csv"), "--dem", str(tmp_path / "no_dem"),
            "--entrances", str(tmp_path / "ent.csv"), "--elevation", str(tmp_path / "none.csv"),
            "--points", str(tmp_path / "none.csv"), "-o", str(out), "--stats", str(stats), "--paths", str(paths),
            "--extra", str(tmp_path / "dorms.csv"), "--flat", str(flat), "--patch", str(patch)]
    assert st.main(args) == 0
    t = {(r["from"], r["to"]): float(r["minutes"]) for r in csv.DictReader(open(out, encoding="utf-8"))}
    rows = {(r["from"], r["to"]): r for r in csv.DictReader(open(stats, encoding="utf-8-sig"))}
    assert set(t) == {(a, b) for a in "ABDE" for b in "ABDE" if a != b}  # F 는 이동시간을 내지 않는다
    ad = rows[("A", "D")]
    assert ad["magicmap_min"] == "" and float(ad["route_m"]) == pytest.approx(145, abs=1)  # 100 m + 40 m + 패치 출입구 5 m
    assert t[("A", "D")] == pytest.approx(float(ad["route_slope_min"]), abs=0.01) and t[("A", "D")] > t[("D", "A")]
    assert t[("A", "B")] == pytest.approx(200 / 1.1 / 60 * math.exp(0.35), rel=1e-3)  # 표 쌍은 그대로 표 × 경사 계수
    f = {(r["from"], r["to"]): r for r in csv.DictReader(open(flat, encoding="utf-8"))}
    assert f[("A", "B")]["source"] == "magicmap" and f[("A", "X")]["source"] == "measured"  # 다른 출처는 그대로
    assert ("A", "Z") not in f  # 이번에 안 나온 옛 route 행은 지운다
    assert f[("A", "D")]["source"] == "route" and float(f[("A", "D")]["minutes"]) == pytest.approx(145 / 1.1 / 60, abs=0.01)
    shapes = json.loads(paths.read_text(encoding="utf-8"))["paths"]
    assert "A|D" in shapes and "B|E" in shapes and "D|E" not in shapes  # 기숙사 동끼리는 그리지 않는다


def test_apply_patch():
    """그래프 패치: 받은 노드·엣지는 그대로, 더한 것은 src = ttwizard. 길 끝은 노드(3 m)·엣지(20 m)에 잇는다."""
    gp = pytest.importorskip("graph_patch")
    g = _graph()
    before_nodes = json.loads(json.dumps(g["nodes"]))
    before_edges = json.loads(json.dumps(g["edges"]))

    def lonlat(x, y):
        a, b = PROJ.inv(x, y)
        return [float(np.ravel(a)[0]), float(np.ravel(b)[0])]

    feats = [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [lonlat(15, 25), lonlat(15, 75)]},
         "properties": {"type": "path", "kind": "footway", "costFactor": 1, "osm": 123}},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [lonlat(60, 110), lonlat(50, 101)]},
         "properties": {"type": "path", "role": "entrance_link", "kind": "footway", "costFactor": 1, "building": "906"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": lonlat(60, 110)},
         "properties": {"type": "entrance", "building": "906"}},
    ]
    gp.apply_patch(g, feats, PROJ)
    assert g["nodes"][:len(before_nodes)] == before_nodes and g["edges"][:len(before_edges)] == before_edges
    new_nodes, new_edges = g["nodes"][len(before_nodes):], g["edges"][len(before_edges):]
    assert all(n["src"] == "ttwizard" and n["id"] > 11 for n in new_nodes)
    assert all(e["src"] == "ttwizard" and e["id"] > len(before_edges) for e in new_edges)
    xy = {n["id"]: tuple(np.round(np.ravel(PROJ.fwd(n["lng"], n["lat"])), 2)) for n in g["nodes"]}
    # 길 양 끝: 노드 1~2, 2~3 엣지 위 수선의 발(0, 25)·(0, 75)에 새 노드 + 원래 엣지를 나눈 엣지(split_of) + 15 m 접속선
    feet = [i for i, p in xy.items() if p in ((0.0, 25.0), (0.0, 75.0))]
    assert len(feet) == 2
    splits = [e for e in new_edges if e.get("split_of")]
    assert len(splits) == 8 and {e["split_of"] for e in splits} <= {1, 3}
    conns = [e for e in new_edges if e.get("connector")]
    assert len(conns) == 4 and all(e["distance"] == pytest.approx(15, abs=0.01) for e in conns)
    main = [e for e in new_edges if e.get("osm") == 123 and not e.get("connector")]
    assert len(main) == 2 and main[0]["distance"] == pytest.approx(50, abs=0.01)
    # 출입구 접속선: 건물 쪽 끝은 출입구 노드(building), 길 쪽 끝은 3 m 안의 노드 4(50, 100)에 붙는다
    door = [n for n in new_nodes if n.get("entrance")]
    assert len(door) == 1 and door[0]["building"] == "906"
    link = [e for e in new_edges if e.get("role") == "entrance_link"]
    assert {(e["from"], e["to"]) for e in link} == {(door[0]["id"], 4), (4, door[0]["id"])}
    # 경사 계산이 더한 그래프에서도 돈다
    ele, res, index = gs.compute(g, FakeDem(), PROJ, np.zeros((0, 2)), np.zeros((0, 2)))
    assert len(ele) == len(g["nodes"]) and all(np.isfinite(ele[index[n["id"]]]) for n in new_nodes)


def test_patch_entrances_reported(tmp_path):
    """사용자 제보(replace = true) 출입구가 있는 동은 그것만 쓰고, 패치를 다시 만들 때도 그 동은 건너뛴다."""
    gp = pytest.importorskip("graph_patch")
    auto = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [126.9579, 37.4618]},
         "properties": {"type": "entrance", "building": "901", "source": "추정"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [126.9574, 37.4614]},
         "properties": {"type": "entrance", "building": "902", "source": "추정"}}]}
    manual = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [126.9577, 37.4620]},
         "properties": {"type": "entrance", "building": "901", "replace": True, "source": "사용자 제보"}}]}
    (tmp_path / "dorm.geojson").write_text(json.dumps(auto), encoding="utf-8")
    (tmp_path / "manual.geojson").write_text(json.dumps(manual), encoding="utf-8")
    e = gp.patch_entrances([tmp_path])
    assert e["901"] == [(126.9577, 37.462)] and e["902"] == [(126.9574, 37.4614)]
    if pytest.importorskip("shapely") and (ROOT / "data" / "dorm_buildings.csv").exists():
        fc = gp.build(manual=[tmp_path / "manual.geojson"])
        doors = {f["properties"]["building"] for f in fc["features"] if f["properties"]["type"] == "entrance"}
        links = {f["properties"]["building"] for f in fc["features"] if f["properties"].get("role") == "entrance_link"}
        assert "901" not in doors and "901" not in links and "902" in doors


def _ll(x, y):
    a, b = PROJ.inv(x, y)
    return [float(np.ravel(a)[0]), float(np.ravel(b)[0])]


def test_apply_patch_exact_ends():
    """손으로 그린 패치: snap·link 를 작게 주면 정확히 둔 끝만 붙는다. 같은 엣지에 두 번 붙으면 조각을 나눠 이어지고,
    짧은 접속선이 제 출입구 노드에 붙지 않는다."""
    gp = pytest.importorskip("graph_patch")
    g = _graph()
    n0 = len(g["nodes"])
    feats = [
        # 엣지 1–2 (0,0)–(0,50) 에 두 출입구가 y = 20, 30 에서 붙는다
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [_ll(5, 20), _ll(0, 20)]},
         "properties": {"type": "path", "role": "entrance_link", "building": "A", "snap": 0.5, "link": 1.0}},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [_ll(5, 30), _ll(0, 30)]},
         "properties": {"type": "path", "role": "entrance_link", "building": "B", "snap": 0.5, "link": 1.0}},
        # 노드 2(0, 50)에서 1.5 m: snap 0.5 라 노드가 아니라 엣지 2–3 위 (0, 51.5)에 붙는다
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [_ll(20, 51.5), _ll(0, 51.5)]},
         "properties": {"type": "path", "kind": "footway", "snap": 0.5, "link": 1.0}},
        # 기본 snap(3 m) 접속선 2.5 m: 제 출입구 노드가 아니라 엣지 2–3 위 (0, 75)에 붙는다
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [_ll(2.5, 75), _ll(0, 75)]},
         "properties": {"type": "path", "role": "entrance_link", "building": "C"}},
    ]
    gp.apply_patch(g, feats, PROJ)
    xy = {n["id"]: tuple(np.round(np.ravel(PROJ.fwd(n["lng"], n["lat"])), 1)) for n in g["nodes"]}
    at = {p: i for i, p in xy.items()}
    adj = {}
    for e in g["edges"][18:]:
        adj.setdefault(e["from"], {})[e["to"]] = e["distance"]
    f20, f30 = at[(0.0, 20.0)], at[(0.0, 30.0)]
    assert adj[f20][f30] == pytest.approx(10, abs=0.01)  # 두 번째 분할은 첫 조각을 나눈다
    assert adj[1][f20] == pytest.approx(20, abs=0.01) and adj[f30][2] == pytest.approx(20, abs=0.01)
    assert all(e.get("split_of") in (1, 2, 3, 4) for e in g["edges"][18:] if e.get("split_of") is not None)
    f515 = at[(0.0, 51.5)]
    assert f515 > n0 and adj[f515][at[(20.0, 51.5)]] == pytest.approx(20, abs=0.01)
    doors = {n["building"]: n["id"] for n in g["nodes"] if n.get("entrance")}
    assert adj[doors["C"]][at[(0.0, 75.0)]] == pytest.approx(2.5, abs=0.01)
    assert not any(e.get("connector") for e in g["edges"][18:])


def test_router_starts_at_door():
    """출입구 노드 자리의 출입구는 그 노드에서만 출발한다(20 m 안의 다른 길로 벽을 넘는 직선 접속을 하지 않는다)."""
    pts = {1: (0, 0), 2: (0, 100), 3: (10, 0), 4: (10, 50), 5: (6, 50)}
    lon, lat = PROJ.inv([p[0] for p in pts.values()], [p[1] for p in pts.values()])
    nodes = [{"id": i, "lng": float(a), "lat": float(b), "ele": 100.0} for i, a, b in zip(pts, lon, lat)]
    nodes[4]["entrance"], nodes[4]["building"] = True, "D"
    edges, k = [], 0
    for a, b in [(1, 2), (1, 3), (3, 4), (4, 5)]:
        d = float(np.hypot(*(np.subtract(pts[b], pts[a]))))
        for u, v in ((a, b), (b, a)):
            k += 1
            edges.append({"id": k, "from": u, "to": v, "distance": d, "walkable": True, "isTunnel": False})
    r = st.Router({"nodes": nodes, "edges": edges}, PROJ)
    lon5, lat5 = PROJ.inv(6.0, 50.0)
    att = r.attach(float(np.ravel(lon5)[0]), float(np.ravel(lat5)[0]))
    assert list(att) == [4] and att[4][0] == 0.0  # 노드 5(출입구, 인덱스 4)만. 6 m 옆 엣지 1–2 에는 붙지 않는다
    lon0, lat0 = PROJ.inv(3.0, 50.0)  # 출입구 노드가 아닌 곳은 예전처럼 가까운 길들에 붙는다
    assert len(st.Router({"nodes": nodes, "edges": edges}, PROJ).attach(float(np.ravel(lon0)[0]), float(np.ravel(lat0)[0]))) > 1
    out = r.routes({"D": [(float(np.ravel(lon5)[0]), float(np.ravel(lat5)[0]))], "N": [tuple(_ll(0, 100))]})
    s, z, geom = out[("D", "N")]
    assert float(s[-1]) == pytest.approx(4 + 50 + 10 + 100, abs=0.01)  # 5→4→3→1→2: 벽 너머 6 m 직선 대신 실제 길


def test_reported_entrances_win(tmp_path):
    """replace = true 출입구(손으로 그린 패치·사용자 제보)는 building_entrances.csv 의 출입구보다 우선한다."""
    _write_csv(tmp_path / "ent.csv", ["building", "lat", "lon"], [("X", 37.4600, 126.9500), ("Y", 37.4610, 126.9510)])
    patch = tmp_path / "patch"
    patch.mkdir()
    (patch / "m.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [126.9502, 37.4602]},
         "properties": {"type": "entrance", "building": "X", "replace": True}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [126.9512, 37.4612]},
         "properties": {"type": "entrance", "building": "Y"}}]}), encoding="utf-8")
    pts = st.load_points(["X", "Y"], tmp_path / "ent.csv", tmp_path / "none.csv", tmp_path / "none.csv", None, [patch])
    assert pts["X"] == [(126.9502, 37.4602)] and pts["Y"] == [(126.951, 37.461)]


def test_build_skips_curated_area(tmp_path):
    """손으로 그린 패치의 type = area 안에서는 OSM 길·출입구를 자동으로 만들지 않는다."""
    gp = pytest.importorskip("graph_patch")
    pytest.importorskip("shapely")
    if not (ROOT / "data" / "dorm_buildings.csv").exists():
        pytest.skip("기숙사 목록 없음")
    lon, lat = 126.9578, 37.4620  # 901동 둘레
    d = 0.0012
    area = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d],
                                                                            [lon - d, lat + d], [lon - d, lat - d]]]},
         "properties": {"type": "area"}}]}
    (tmp_path / "area.geojson").write_text(json.dumps(area), encoding="utf-8")
    base = gp.build(manual=[])
    fc = gp.build(manual=[tmp_path / "area.geojson"])
    doors = lambda c: {f["properties"]["building"] for f in c["features"] if f["properties"]["type"] == "entrance"}  # noqa: E731
    assert "901" in doors(base) and "901" not in doors(fc) and "931" in doors(fc)
    from shapely.geometry import box, shape
    A = box(lon - d, lat - d, lon + d, lat + d)
    runs = [f for f in fc["features"] if f["properties"]["type"] == "path" and f["properties"].get("role") != "entrance_link"]
    assert runs and not any(shape(f["geometry"]).intersects(A) for f in runs)


def test_base_route_and_back(tmp_path):
    """--base route: 표에 있는 쌍도 우리 경로의 경사 반영 시간을 그대로 쓰고, travel.csv 의 표 쌍(source = magicmap)을 우리 경로
    평지 시간(source = route)으로 바꾼다(실측 행은 그대로). 다시 magicmap 기준으로 돌리면 표 값으로 돌아온다."""
    pts = {1: (0, 0), 2: (0, 200)}
    lon, lat = PROJ.inv([p[0] for p in pts.values()], [p[1] for p in pts.values()])
    nodes = [{"id": i, "lng": float(a), "lat": float(b), "ele": 100 + 0.1 * pts[i][1]} for i, a, b in zip(pts, lon, lat)]
    edges = [{"id": k + 1, "from": u, "to": v, "distance": 200.0, "kind": "footway", "walkable": True, "isTunnel": False,
              "surface": "ground"} for k, (u, v) in enumerate(((1, 2), (2, 1)))]
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"nodes": nodes, "edges": edges}), encoding="utf-8")

    def ll(x, y):
        a, b = PROJ.inv(x, y)
        return float(np.ravel(b)[0]), float(np.ravel(a)[0])

    _write_csv(tmp_path / "ent.csv", ["building", "lat", "lon"], [("A", *ll(0, 0)), ("B", *ll(0, 200))])
    # 표는 이 쌍을 400 m(끊긴 그래프로 돌아간 값)로 알고 있다: 400 ÷ 1.1 m/s
    _write_csv(tmp_path / "pairs.csv", ["from", "to", "distance_m", "time_s"],
               [("A", "B", 400, 400 / 1.1), ("B", "A", 400, 400 / 1.1)])
    flat = tmp_path / "travel.csv"
    flat.write_text("from,to,minutes,source\nA,B,6.06,magicmap\nB,A,7.00,measured\n", encoding="utf-8")
    out, stats, paths = tmp_path / "travel_slope.csv", tmp_path / "stats.csv", tmp_path / "paths.json"
    args = ["--graph", str(graph), "--pairs", str(tmp_path / "pairs.csv"), "--dem", str(tmp_path / "no_dem"),
            "--entrances", str(tmp_path / "ent.csv"), "--elevation", str(tmp_path / "none.csv"),
            "--points", str(tmp_path / "none.csv"), "-o", str(out), "--stats", str(stats), "--paths", str(paths),
            "--extra", "", "--flat", str(flat), "--patch"]
    read = lambda p, enc="utf-8": {(r["from"], r["to"]): r for r in csv.DictReader(open(p, encoding=enc))}  # noqa: E731
    up = 200 / 1.1 / 60 * math.exp(0.35)  # 10 % 오르막 200 m 를 우리 경로로 걷는 시간(분)

    assert st.main(args) == 0  # 기본: 표 시간 × 경사 계수
    assert float(read(out)[("A", "B")]["minutes"]) == pytest.approx(2 * up, rel=1e-3)
    assert read(flat)[("A", "B")] == {"from": "A", "to": "B", "minutes": "6.06", "source": "magicmap"}
    assert read(stats, "utf-8-sig")[("A", "B")]["check"] == "경로 다름"  # 표 6.06분, 우리 경로 3.03분

    assert st.main(args + ["--base", "route"]) == 0
    assert float(read(out)[("A", "B")]["minutes"]) == pytest.approx(up, rel=1e-3)
    assert float(read(out)[("B", "A")]["minutes"]) == pytest.approx(200 / 1.1 / 60, rel=1e-3)
    f = read(flat)
    assert f[("A", "B")]["source"] == "route" and float(f[("A", "B")]["minutes"]) == pytest.approx(200 / 1.1 / 60, abs=0.01)
    assert f[("B", "A")] == {"from": "B", "to": "A", "minutes": "7.00", "source": "measured"}
    row = read(stats, "utf-8-sig")[("A", "B")]
    assert row["minutes"] == row["route_slope_min"] and float(row["magicmap_min"]) == pytest.approx(400 / 1.1 / 60, abs=0.01)

    assert st.main(args) == 0  # 되돌리기: 표 쌍의 route 행이 표 값으로 돌아온다
    assert float(read(out)[("A", "B")]["minutes"]) == pytest.approx(2 * up, rel=1e-3)
    assert read(flat)[("A", "B")] == {"from": "A", "to": "B", "minutes": "6.06", "source": "magicmap"}
    assert read(flat)[("B", "A")]["source"] == "measured"


def test_load_points_alias(tmp_path):
    """제 출입구 → 제 좌표 → (둘 다 없을 때만) 대신 쓸 건물(ALIASES) 순. 71-1동은 이제 좌표·출입구가 있어 71동을 대신 쓰지 않는다."""
    _write_csv(tmp_path / "ent.csv", ["building", "lat", "lon"], [("71", 37.4670, 126.9520)])
    _write_csv(tmp_path / "list.csv", ["building", "lat", "lon"], [("71-1", 37.46649, 126.95268)])
    none = tmp_path / "none.csv"
    assert st.load_points(["71-1"], tmp_path / "ent.csv", none, none) == {"71-1": [(126.9520, 37.4670)]}       # 아무것도 없으면 71동
    assert st.load_points(["71-1"], tmp_path / "ent.csv", none, tmp_path / "list.csv") == {"71-1": [(126.95268, 37.46649)]}
    data = ROOT / "data"
    listing = {r["building"]: r for r in st._rows(data / "buildings_for_magicmap.csv")}
    gate = listing["GATE"]
    assert (float(gate["lat"]), float(gate["lon"])) == pytest.approx((37.46635, 126.94832), abs=1e-6)  # 정문 구조물 자리(로드뷰로 확인)
    assert listing["71-1"]["lat"] and listing["71-1"]["lon"]
    pts = st.load_points(["71-1", "71", "GATE"], extra=data / "dorm_buildings.csv", patch=[data / "graph_patch"])
    assert pts["71-1"] != pts["71"] and len(pts["GATE"]) >= 1
