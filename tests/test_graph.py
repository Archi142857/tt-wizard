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
            "--points", str(tmp_path / "none.csv"), "-o", str(out), "--stats", str(stats), "--paths", str(paths)]
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
