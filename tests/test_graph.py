"""도로 그래프 경사(graph_slopes.py)와 건물쌍 거리표 변환(magicmap_travel.py) 테스트. DEM은 가짜 함수로 대신한다."""

import csv
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

be = pytest.importorskip("building_elevation")
gs = pytest.importorskip("graph_slopes")
import magicmap_travel as mt  # noqa: E402
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
