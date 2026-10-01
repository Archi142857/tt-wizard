"""바탕 지도(data/basemap.json, scripts/basemap.py, scripts/fetch_osm_basemap.py) 테스트.

파일 형식 검사는 표준 라이브러리만 쓴다. 만들기 검사는 shapely·pyproj·pyshp 가 있을 때만(작은 가짜 도엽으로).
"""

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import basemap as bm  # noqa: E402

FILE = ROOT / "data" / "basemap.json"


def _campus_bounds():
    lat, lon = [], []
    with open(ROOT / "data" / "campus_buildings.csv", newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("lat") and r.get("lon"):
                lat.append(float(r["lat"]))
                lon.append(float(r["lon"]))
    dl, dn = (max(lat) - min(lat)) * 0.1, (max(lon) - min(lon)) * 0.1  # 화면의 campusBounds.pad(0.1) 과 같게
    return min(lat) - dl, min(lon) - dn, max(lat) + dl, max(lon) + dn


def test_polyline_round_trip():
    pts = [(37.459012, 126.952345), (37.459013, 126.952345), (37.4601, 126.9499), (37.45, 126.96)]
    for prec in (5, 6):
        back = bm.decode(bm.encode_latlon(pts, prec), prec)
        assert len(back) == len(pts) - (1 if prec == 5 else 0)  # 소수 5자리에서는 처음 두 점이 같아져 하나로
        for (a, b), (c, d) in zip(back, [p for i, p in enumerate(pts) if not (prec == 5 and i == 1)]):
            assert abs(a - c) <= 0.6 / 10 ** prec and abs(b - d) <= 0.6 / 10 ** prec


@pytest.mark.skipif(not FILE.exists(), reason="data/basemap.json 없음")
def test_basemap_file():
    raw = FILE.read_bytes()
    assert len(raw) < 700_000  # 앱 설치 파일·첫 방문 크기
    d = json.loads(raw)
    assert d["v"] == 1 and any("국토지리정보원" in s for s in d["src"]) and any("OpenStreetMap" in s for s in d["src"])
    s, w, n, e = d["bounds"]
    cs, cw, cn, ce = _campus_bounds()
    # 캠퍼스(+10 %)가 범위 안에 여유 있게 들어간다(300 m 넘게)
    assert s < cs - 0.003 and w < cw - 0.003 and n > cn + 0.003 and e > ce + 0.003
    for k in ("building", "road", "water", "campus", "green"):
        assert d["area"][k], k
    n_pts = 0
    for k, items in d["area"].items():
        for item in items:
            prec, rings = item[0], item[1:]
            assert prec in (5, 6) and rings and all(isinstance(r, str) and r for r in rings), k
            for lat, lon in bm.decode(rings[0], prec)[::7]:
                assert s - 1e-4 <= lat <= n + 1e-4 and w - 1e-4 <= lon <= e + 1e-4, k
                n_pts += 1
    assert n_pts > 1000
    for k, items in d["line"].items():
        assert k in ("road", "pedestrian", "walk", "steps") and all(isinstance(kind, str) and isinstance(p, str) for kind, p in items)
    assert d["line"]["walk"] and d["line"]["steps"]
    assert all(z % 5 == 0 for z, _ in d["contour"]["minor"]) and all(z % 25 == 0 for z, _ in d["contour"]["index"])
    # OSM 숲·잔디 자료가 레포에 있으면 어림이 아니라 그것으로 칠했어야 한다
    assert d["green_approx"] is not (ROOT / "data" / "osm_basemap.geojson").exists()


# ---------------------------------------------------------------- 만들기 (작은 가짜 도엽)

def _write_sheet(root: Path, proj):
    import shapefile

    d = root / "(B010)수치지도_37612018_2025_00000000000000"
    d.mkdir(parents=True)
    x0, y0 = proj.tm(126.9520, 37.4590)

    def sq(cx, cy, r):
        return [[(cx - r, cy - r), (cx - r, cy + r), (cx + r, cy + r), (cx + r, cy - r), (cx - r, cy - r)]]

    def poly(name, shapes, fields=()):
        w = shapefile.Writer(str(d / name), shapeType=shapefile.POLYGON, encoding="cp949")
        w.field("UFID", "C", 20)
        for f in fields:
            w.field(*f)
        for i, (parts, rec) in enumerate(shapes):
            w.poly(parts)
            w.record(f"U{i}", *rec)
        w.close()
        (d / f"{name}.cpg").write_text("EUC-KR", encoding="ascii")  # 국토정보플랫폼 SHP 처럼

    poly("N3A_B0010000", [(sq(x0, y0, 15), []), (sq(x0 + 60, y0, 10), []), (sq(x0 + 1500, y0 + 100, 8), [])])
    poly("N3A_A0010000", [([[(x0 - 400, y0 - 40), (x0 - 400, y0 - 25), (x0 + 400, y0 - 25), (x0 + 400, y0 - 40), (x0 - 400, y0 - 40)]], []),
                          ([[(x0 - 400, y0 + 200), (x0 - 400, y0 + 230), (x0 + 400, y0 + 230), (x0 + 400, y0 + 200), (x0 - 400, y0 + 200)]], [])])
    poly("N3A_A0033320", [(sq(x0, y0 - 50, 4), [])])
    poly("N3A_E0052114", [(sq(x0 - 200, y0 + 100, 20), [])])
    w = shapefile.Writer(str(d / "N3L_F0010000"), shapeType=shapefile.POLYLINE, encoding="cp949")
    w.field("UFID", "C", 20)
    w.field("구분", "C", 10)
    w.field("등고수치", "N", 10, 2)
    for i, (kind, z, dy) in enumerate((("주곡선", 95, -300), ("계곡선", 100, 0), ("주곡선", 105, 300))):
        w.line([[(x0 - 2000, y0 + dy), (x0 - 600, y0 + dy + 40), (x0, y0 + dy + 10), (x0 + 2000, y0 + dy)]])
        w.record(f"C{i}", kind, z)
    w.close()
    (d / "N3L_F0010000.cpg").write_text("EUC-KR", encoding="ascii")
    return d, (x0, y0)


def test_build_from_small_sheet(tmp_path):
    pytest.importorskip("shapely")
    pytest.importorskip("pyproj")
    pytest.importorskip("shapefile")
    proj = bm.Proj()
    topo = tmp_path / "topo"
    _write_sheet(topo, proj)
    campus = tmp_path / "campus.csv"
    campus.write_text("building,lat,lon\n1,37.4590,126.9520\n2,37.4595,126.9527\n", encoding="utf-8")
    # OSM: 큰길(남쪽 도로면과 겹친다), 캠퍼스 안 찻길·보행로·계단, 실내 통로(빠져야 한다)
    lon0, lat0 = 126.9520, 37.4590
    k = 1 / 111000

    def ls(hw, pts, **extra):
        return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": pts}, "properties": {"highway": hw, **extra}}

    paths = tmp_path / "osm_paths.geojson"
    paths.write_text(json.dumps({"type": "FeatureCollection", "features": [
        ls("trunk", [[lon0 - 450 * k * 1.26, lat0 - 32 * k], [lon0 + 450 * k * 1.26, lat0 - 32 * k]]),
        ls("service", [[lon0, lat0 + 30 * k], [lon0 + 100 * k * 1.26, lat0 + 30 * k]]),
        ls("footway", [[lon0, lat0 + 40 * k], [lon0 + 80 * k * 1.26, lat0 + 60 * k]]),
        ls("steps", [[lon0 + 10 * k, lat0 + 70 * k], [lon0 + 30 * k * 1.26, lat0 + 75 * k]]),
        ls("corridor", [[lon0, lat0], [lon0 + 20 * k, lat0]], indoor="yes"),
    ]}), encoding="utf-8")
    d = bm.build(topo=topo, osm_basemap=tmp_path / "없음.geojson", osm_paths=paths, campus=campus)
    assert d["green_approx"] is True and d["area"]["green"]
    assert len(d["area"]["building"]) == 3 and d["area"]["water"] and d["area"]["walk"]
    assert d["area"].get("road_trunk") and d["area"].get("road")  # 큰길과 겹친 도로면만 큰길 색
    assert {k for k in d["line"]} == {"road", "walk", "steps"}  # 실내 통로는 빠진다
    assert [z for z, _ in d["contour"]["index"]] and all(z == 100 for z, _ in d["contour"]["index"])
    assert sorted({z for z, _ in d["contour"]["minor"]}) == [95, 105]
    s, w, n, e = d["bounds"]
    assert s < lat0 < n and w < lon0 < e
    # 가까운 건물은 소수 6자리, 먼 건물(1.5 km 밖)은 5자리
    assert sorted(item[0] for item in d["area"]["building"]) == [5, 6, 6]


# ---------------------------------------------------------------- OSM 받기(면 조립)

def test_fetch_osm_basemap_assembles_areas():
    pytest.importorskip("requests")
    import fetch_osm_basemap as fob

    def g(*pts):
        return [{"lon": x, "lat": y} for x, y in pts]

    data = {"elements": [
        {"type": "way", "id": 1, "tags": {"landuse": "forest"}, "geometry": g((0, 0), (0, 1), (1, 1), (0, 0))},
        {"type": "way", "id": 2, "tags": {"natural": "wood"}, "geometry": g((0, 0), (0, 1), (1, 1))},  # 닫히지 않음 → 뺀다
        {"type": "way", "id": 3, "tags": {"amenity": "parking"}, "geometry": g((0, 0), (0, 1), (1, 1), (0, 0))},  # 다른 태그
        {"type": "relation", "id": 4, "tags": {"leisure": "park", "type": "multipolygon"}, "members": [
            {"type": "way", "role": "outer", "geometry": g((0, 0), (0, 10), (10, 10))},
            {"type": "way", "role": "outer", "geometry": g((10, 10), (10, 0), (0, 0))},
            {"type": "way", "role": "inner", "geometry": g((2, 2), (2, 3), (3, 3), (2, 2))},
            {"type": "way", "role": "outer", "geometry": g((20, 20), (20, 21), (21, 21), (20, 20))},
        ]},
    ]}
    feats = fob.to_areas(data)
    assert [(f["properties"]["osm_id"], f["properties"]["kind"]) for f in feats] == [(1, "green"), (4, "park")]
    rel = feats[1]["geometry"]
    assert rel["type"] == "MultiPolygon" and len(rel["coordinates"]) == 2
    assert len(rel["coordinates"][0]) == 2 and len(rel["coordinates"][1]) == 1  # 첫 고리에만 구멍
    lines = fob.to_lines({"elements": [{"type": "way", "id": 9, "tags": {"highway": "footway"}, "nodes": [1, 2],
                                        "geometry": g((0, 0), (1, 1))}]})
    assert lines[0]["properties"]["highway"] == "footway" and "nodes" not in lines[0]["properties"]
    # 한 번에 받으면 서버가 504 를 내서 나눠 받는다: 면은 태그마다, 선은 넓은 것·캠퍼스 둘레
    areas = fob.area_queries("1,2,3,4")
    assert [label for label, _ in areas] == ["면 landuse", "면 leisure", "면 natural"]
    assert 'way["landuse"~"^(forest|grass|meadow|recreation_ground|village_green)$"](1,2,3,4)' in areas[0][1]
    wide, near = fob.line_queries("1,2,3,4", "5,6,7,8")
    assert "footway" in wide[1] and "residential" not in wide[1] and "residential" in near[1] and "(5,6,7,8)" in near[1]


def test_overpass_treats_runtime_error_as_failure(monkeypatch):
    requests = pytest.importorskip("requests")
    import fetch_osm_basemap as fob

    calls = []

    class Res:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def post(url, **kw):
        calls.append(url.split("/")[2])
        if len(calls) == 1:  # 첫 서버: 200 이지만 시간 초과 표시(결과가 잘림)
            return Res({"remark": 'runtime error: Query timed out in "query" at line 1 after 181 seconds.', "elements": []})
        return Res({"elements": [{"type": "way", "id": 1}]})

    monkeypatch.setattr(requests, "post", post)
    data = fob.overpass("[out:json];", rounds=1)
    assert data == {"elements": [{"type": "way", "id": 1}]} and len(calls) == 2
