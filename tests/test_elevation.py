"""건물 고도·출입구 파이프라인 테스트 (네트워크 없이). DEM은 기울어진 평면을 가짜로 만들어 쓴다."""

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import building_elevation as be  # noqa: E402
import fetch_campus_buildings as fcb  # noqa: E402
import fetch_osm_footprints as fof  # noqa: E402

P_LAT, P_LON = 37.4590, 126.9520  # 가짜 건물 위치
GRAD_N, GRAD_E = 0.10, 0.02       # 북쪽으로 10 %, 동쪽으로 2 % 오르는 평면


def _plane(x, y, x0, y0):
    return 100.0 + GRAD_N * (y - y0) + GRAD_E * (x - x0)


@pytest.fixture(scope="module")
def dem(tmp_path_factory):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    from rasterio.warp import transform as warp

    x0, y0 = (v[0] for v in warp("EPSG:4326", "EPSG:5186", [P_LON], [P_LAT]))
    res, n = 5.0, 800  # 5 m 격자, 4 km
    left, top = x0 - res * n / 2, y0 + res * n / 2
    cols = left + res * (np.arange(n) + 0.5)
    rows = top - res * (np.arange(n) + 0.5)
    xx, yy = np.meshgrid(cols, rows)
    arr = _plane(xx, yy, x0, y0).astype("float32")
    path = tmp_path_factory.mktemp("dem") / "plane.tif"
    with rasterio.open(path, "w", driver="GTiff", width=n, height=n, count=1, dtype="float32",
                       crs="EPSG:5186", transform=from_origin(left, top, res, res), nodata=-9999) as ds:
        ds.write(arr, 1)
    d = be.Dem([path])
    d.origin = (x0, y0)
    return d


def _truth(dem, lons, lats):
    from rasterio.warp import transform as warp
    xs, ys = warp("EPSG:4326", "EPSG:5186", list(lons), list(lats))
    return _plane(np.asarray(xs), np.asarray(ys), *dem.origin)


def _lonlat(proj, pts):
    lon, lat = proj.inv([p[0] for p in pts], [p[1] for p in pts])
    return [[float(a), float(b)] for a, b in zip(np.atleast_1d(lon), np.atleast_1d(lat))]


def _square(proj, cx, cy, half):
    return _lonlat(proj, [(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half),
                          (cx - half, cy + half), (cx - half, cy - half)])


def _geojson(tmp_path, name, feats):
    p = tmp_path / name
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    return p


def _poly(ring, props):
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": props}


def _one(lat=P_LAT, lon=P_LON, b="301"):
    return {b: {"building": b, "name": "시험동", "lat": lat, "lon": lon, "source": "t"}}


def test_bilinear_reproduces_plane(dem):
    rng = np.random.default_rng(0)
    lons = P_LON + rng.uniform(-0.01, 0.01, 50)
    lats = P_LAT + rng.uniform(-0.01, 0.01, 50)
    assert np.allclose(dem.sample(lons, lats), _truth(dem, lons, lats), atol=1e-3)
    assert np.isnan(dem.sample([P_LON + 0.2], [P_LAT])[0])  # 범위 밖


def test_first_floor_is_perimeter_weighted_mean(dem, tmp_path):
    proj = be.LocalProj()
    px, py = (float(v) for v in proj.fwd(P_LON, P_LAT))
    fps = be.load_footprints(_geojson(tmp_path, "fp.geojson", [_poly(_square(proj, px, py, 20),
                                                                          {"osm_type": "way", "osm_id": 1})]), proj)
    rows, ents = be.estimate(_one(), fps, dem, proj)
    r = rows[0]
    center = float(_truth(dem, [P_LON], [P_LAT])[0])
    assert r["footprint"] == "osm-way/1" and r["footprint_match"] == "inside"
    # 40 m 정사각형 둘레 평균 = 중심 고도, 고도차 ≈ 40 m × (10 % + 2 %)
    assert abs(float(r["first_floor_est_m"]) - center) <= 0.1
    assert 4.4 <= float(r["ground_span_m"]) <= 4.9
    assert r["slope_site"] == "Y" and r["perimeter_m"] == "160"
    assert abs(float(r["point_ground_m"]) - center) <= 0.1
    # 출입구 정보가 없는 경사지 → 로비층은 비워 둔다
    assert ents == [] and r["entrances"] == "0" and r["lobby_est_m"] == ""
    assert "로비층 확정 필요(경사지, 출입구 정보 없음)" in r["note"]


def test_entrances_on_several_levels(dem, tmp_path):
    """남쪽 main 출입구(낮음), 동쪽 보행로 공유 노드, 북쪽 보행로 끝점(높음) → 지하1층/1층/2층."""
    proj = be.LocalProj()
    px, py = (float(v) for v in proj.fwd(P_LON, P_LAT))
    h = 30
    ring = _lonlat(proj, [(px - h, py - h), (px + h, py - h), (px + h, py), (px + h, py + h), (px - h, py + h),
                          (px - h, py - h)])
    fps = be.load_footprints(_geojson(tmp_path, "fp.geojson", [_poly(ring, {
        "osm_type": "way", "osm_id": 1, "nodes": [1, 2, 5, 3, 4, 1]})]), proj)
    pt = lambda x, y, props: {"type": "Feature", "geometry": {"type": "Point", "coordinates": _lonlat(proj, [(x, y)])[0]},  # noqa: E731
                              "properties": props}
    ln = lambda pts, props: {"type": "Feature", "geometry": {"type": "LineString", "coordinates": _lonlat(proj, pts)},  # noqa: E731
                             "properties": props}
    ent_path = _geojson(tmp_path, "ent.geojson", [
        pt(px, py - h, {"osm_id": 10, "entrance": "main"}),        # 남쪽 벽 위 (way 노드는 아님)
        pt(px + 2, py - h - 1, {"osm_id": 12, "entrance": "yes"}),  # 2 m 옆 → 합쳐짐
        pt(px + 100, py + 100, {"osm_id": 11, "entrance": "yes"}),  # 멀리 → 무시
    ])
    path_path = _geojson(tmp_path, "paths.geojson", [
        ln([(px, py + h + 30), (px, py + h + 1)], {"osm_id": 20, "highway": "footway", "nodes": [21, 22]}),
        ln([(px + h + 30, py), (px + h, py)], {"osm_id": 30, "highway": "footway", "nodes": [31, 5]}),
        ln([(px - h - 30, py), (px - h - 1, py)], {"osm_id": 40, "highway": "footway", "bridge": "yes",
                                                    "nodes": [41, 42]}),  # 다리 → 제외
    ])
    rows, ents = be.estimate(_one(), fps, dem, proj, entrances=be.load_points(ent_path, proj),
                             paths=be.load_paths(path_path, proj))
    r = rows[0]
    assert [e["source"] for e in ents] == ["osm-entrance", "osm-path-join", "osm-path-end"]
    assert [e["floor_est"] for e in ents] == ["지하1층", "1층", "2층"]
    assert [e["rel_to_1f_m"] for e in ents] == ["-3.0", "+0.6", "+3.0"]
    assert ents[0]["kind"] == "main" and ents[0]["osm_id"] == "10"
    assert r["entrances"] == "3" and r["entrance_floors"] == "지하1층/1층/2층" and r["multi_level_access"] == "Y"
    assert r["lobby_source"] == "main 출입구" and r["lobby_est_m"] == ents[0]["ground_m"]
    assert "지상 출입구 3곳이 지하1층/1층/2층" in r["note"]


def test_manual_entrances_override(dem, tmp_path):
    proj = be.LocalProj()
    manual = tmp_path / "manual.csv"
    manual.write_text("building,lat,lon,floor,kind,note\n"
                      f"301,{P_LAT - 0.0002},{P_LON},1,main,정문 쪽\n"
                      f"301,{P_LAT + 0.0002},{P_LON},B1,,현장 확인\n"
                      "301,x,y,3,,좌표 오류 → 무시\n", encoding="utf-8")
    m = be.load_manual(manual, proj)
    assert len(m["301"]) == 2 and m["301"][1].floor_checked == "지하1층"
    rows, ents = be.estimate(_one(), [], dem, proj, manual=m, radius=5)
    assert [e["source"] for e in ents] == ["manual", "manual"]
    assert {e["floor_checked"] for e in ents} == {"1층", "지하1층"}
    assert rows[0]["entrance_floors"] == "지하1층/1층" and rows[0]["lobby_source"] == "main 출입구"


def test_parse_floor():
    cases = {"3": 2, "3층": 2, "3F": 2, "1": 0, "B1": -1, "지하1층": -1, "지하 2층": -2, "-1": -1, "0": None, "": None}
    for s, n in cases.items():
        assert be.parse_floor(s) == n, s
    assert [be.floor_label(n) for n in (-2, -1, 0, 1)] == ["지하2층", "지하1층", "1층", "2층"]


def test_ring_fallback_flat_and_missing(dem):
    proj = be.LocalProj()
    lon, lat = P_LON + 0.003, P_LAT - 0.002
    rows, _ = be.estimate({
        "83": {"building": "83", "name": "평지동", "lat": lat, "lon": lon, "source": "t"},
        "999": {"building": "999", "name": "좌표없음", "lat": None, "lon": None, "source": "t"},
        "1000": {"building": "1000", "name": "먼곳", "lat": 37.60, "lon": 127.10, "source": "t"},
    }, [], dem, proj, lectures={"83"}, radius=5)
    by = {r["building"]: r for r in rows}
    assert by["83"]["footprint"] == "ring5m" and "원형 표본" in by["83"]["note"]
    assert abs(float(by["83"]["first_floor_est_m"]) - float(_truth(dem, [lon], [lat])[0])) <= 0.1
    assert by["83"]["slope_site"] == "N" and by["83"]["lobby_source"] == "1층 기준면(평지)"
    assert by["83"]["lecture_building"] == "Y" and by["999"]["lecture_building"] == "N"
    assert by["999"]["note"] == "좌표 없음" and by["1000"]["note"] == "DEM 범위 밖"
    assert [r["building"] for r in rows] == ["83", "999", "1000"]


def test_match_rules():
    proj = be.LocalProj()

    def sq(cx, cy, h):
        return np.column_stack(proj.fwd(*np.asarray(_square(proj, cx, cy, h)).T))

    a = be.Footprint("A", {"ref": ""}, sq(0, 0, 10), 400.0, (-10, -10, 10, 10))
    b = be.Footprint("B", {"ref": "301"}, sq(60, 0, 10), 400.0, (50, -10, 70, 10))
    assert be.match_footprint("83", 0, 0, [a, b])[1] == "inside"
    fp, how = be.match_footprint("83", 25, 0, [a, b])      # 경계에서 15 m
    assert fp is a and how == "near"
    assert be.match_footprint("83", 0, 45, [a, b]) == (None, "none")  # 35 m 떨어짐
    fp, how = be.match_footprint("301", 0, 0, [a, b])      # 좌표는 A 안이지만 ref가 맞는 B
    assert fp is b and how == "ref"


def test_load_buildings_fills_missing_coords(tmp_path):
    campus = tmp_path / "campus.csv"
    campus.write_text("building,name,ename,fac_type,lat,lon\n301,제1공학관,,OTHER,37.45016,126.95259\n"
                      "71-1,체육관 부속동,,SPORTS,,\n", encoding="utf-8")
    manual = tmp_path / "buildings.csv"
    manual.write_text("building,name,lat,lon\n301,다른이름,1,1\n71-1,수동,37.4676,126.95238\nGATE,정문,37.4662,126.949\n",
                      encoding="utf-8")
    rows = be.load_buildings([campus, manual, tmp_path / "없음.csv"])
    assert rows["301"]["name"] == "제1공학관" and rows["301"]["lat"] == 37.45016  # 앞 파일 우선
    assert rows["71-1"]["name"] == "체육관 부속동" and rows["71-1"]["lat"] == 37.4676  # 좌표만 채움
    assert rows["GATE"]["source"] == "buildings.csv"


def test_write_outputs(tmp_path):
    row = {k: "" for k in be.FIELDS}
    row.update(building="75-1", name="제3학생식당", lat="37.459000", lon="126.952000", first_floor_est_m="120.3")
    gj = be.write_outputs([row], tmp_path / "out.csv")
    assert (tmp_path / "out.csv").read_bytes().startswith(b"\xef\xbb\xbf")  # 엑셀용 BOM
    rows = list(csv.DictReader(open(tmp_path / "out.csv", encoding="utf-8-sig")))
    assert rows[0]["building"] == "75-1"
    assert json.loads(gj.read_text(encoding="utf-8"))["features"][0]["geometry"]["coordinates"] == [126.952, 37.459]
    ent = {k: "" for k in be.ENT_FIELDS}
    ent.update(building="75-1", lat="37.459", lon="126.952", floor_est="1층")
    egj = be.write_entrances([ent], tmp_path / "ent.csv")
    assert json.loads(egj.read_text(encoding="utf-8"))["features"][0]["properties"]["floor_est"] == "1층"


def test_campus_items_are_merged():
    found: dict[str, dict] = {}
    fcb.merge_items(found, {"search_list": [
        {"con_type": "F", "fac_type": "OTHER", "vil_dong_nm": "301", "name": "제1공학관", "ename": "Eng #301",
         "lat_val": "37.45016", "lon_val": "126.95259"},
        {"con_type": "B", "fac_type": "10", "vil_dong_nm": "301", "name": "제1공학관 농협ATM",
         "lat_val": "37.45016", "lon_val": "126.95259"},
        {"con_type": "F", "fac_type": "OTHER", "vil_dong_nm": None, "name": "이름만"},
        {"con_type": "F", "fac_type": "SPORTS", "vil_dong_nm": "71-1", "name": "체육관 부속동",
         "lat_val": "489512", "lon_val": "1097434"},
    ]})
    fcb.merge_items(found, {"search_list": [
        {"con_type": "F", "fac_type": "SPORTS", "vil_dong_nm": "301", "name": "제1공학관(체육)",
         "lat_val": "37.45", "lon_val": "126.95"},
    ]})
    assert set(found) == {"301", "71-1"}
    assert found["301"]["name"] == "제1공학관" and found["301"]["fac_type"] == "OTHER"
    assert found["71-1"]["lat"] == ""  # 관악 범위 밖 좌표는 버림
    assert sorted(["43-2", "301", "43", "9", "GATE", "43-10"], key=fcb.building_key) == ["9", "43", "43-2", "43-10", "301", "GATE"]


def test_osm_parsing():
    g = lambda *pts: [{"lat": b, "lon": a} for a, b in pts]  # noqa: E731
    data = {"elements": [
        {"type": "way", "id": 1, "tags": {"building": "yes", "name": "제1공학관", "ref": "301"},
         "nodes": [1, 2, 3, 1], "geometry": g((0, 0), (1, 0), (1, 1), (0, 0))},
        {"type": "way", "id": 2, "tags": {"building": "yes"},  # 닫히지 않은 way는 닫는다
         "nodes": [5, 6, 7], "geometry": g((5, 5), (6, 5), (6, 6))},
        {"type": "relation", "id": 3, "tags": {"building": "university"}, "members": [
            {"type": "way", "role": "outer", "geometry": g((10, 0), (11, 0), (11, 1))},
            {"type": "way", "role": "outer", "geometry": g((10, 0), (10, 1), (11, 1))},
            {"type": "way", "role": "inner", "geometry": g((10.2, 0.2), (10.4, 0.2))},
        ]},
        {"type": "node", "id": 9, "lat": 0.5, "lon": 0, "tags": {"entrance": "main", "level": "0"}},
        {"type": "node", "id": 8, "lat": 0.5, "lon": 1, "tags": {"amenity": "bench"}},
        {"type": "way", "id": 50, "tags": {"highway": "steps"}, "nodes": [9, 60], "geometry": g((0, 0.5), (-1, 0.5))},
        {"type": "way", "id": 51, "tags": {"highway": "footway"}, "nodes": [70, 71], "geometry": [{"lat": 0, "lon": 0}, None]},
    ]}
    feats = fof.to_features(data)
    assert [f["properties"]["osm_id"] for f in feats] == [1, 2, 3]
    assert feats[0]["properties"]["nodes"] == [1, 2, 3, 1] and feats[1]["properties"]["nodes"] == [5, 6, 7, 5]
    for f in feats:
        ring = f["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1] and len(ring) >= 4
    assert len(feats[2]["geometry"]["coordinates"][0]) == 5  # 두 조각을 이어 사각형 하나
    ents = fof.to_entrances(data)
    assert [(e["properties"]["osm_id"], e["properties"]["entrance"], e["properties"]["level"]) for e in ents] == [(9, "main", "0")]
    paths = fof.to_paths(data)
    assert [p["properties"]["osm_id"] for p in paths] == [50]  # 좌표가 빠진 51은 점 1개라 제외
    assert paths[0]["properties"]["nodes"] == [9, 60] and paths[0]["properties"]["highway"] == "steps"
