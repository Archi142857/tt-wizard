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
import dem_from_contours as dfc  # noqa: E402
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
    d.src_path = path
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


def test_dem_reads_only_campus_window(dem):
    src = dem.src_path
    small = be.Dem([src], bbox=(P_LAT - 0.002, P_LON - 0.002, P_LAT + 0.002, P_LON + 0.002))
    layer = small.layers[0]
    assert layer.full_size == (800, 800) and layer.arr.shape[0] < 120 and layer.arr.shape[1] < 120
    lons, lats = [P_LON, P_LON + 0.0015], [P_LAT, P_LAT - 0.0015]
    assert np.allclose(small.sample(lons, lats), _truth(dem, lons, lats), atol=1e-3)
    assert np.isnan(small.sample([P_LON + 0.01], [P_LAT])[0])  # 읽은 범위 밖
    far = be.Dem([src], bbox=(38.0, 128.0, 38.1, 128.1))  # 겹치지 않는 도엽은 건너뜀
    assert far.layers == [] and far.skipped == ["plane.tif"]


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


def _write_topo(tmp_path, x0, y0, sheet="37612018", prefix="N3", contours=True, spots=((10, 20, 102.0),),
                buildings=(("공과대학301동시험관", 5),)):
    """가짜 수치지형도 도엽 폴더: 동서로 뻗은 등고선(50 m마다 5 m씩 높아짐 = 북쪽 10 % 경사), 표고점, 건물(40 m 정사각형)."""
    shapefile = pytest.importorskip("shapefile")
    from rasterio.crs import CRS

    d = tmp_path / "topo" / f"(B010)수치지도_{sheet}_2025_0001"
    d.mkdir(parents=True)
    wkt = CRS.from_epsg(5186).to_wkt()
    stems = []
    if contours:
        w = shapefile.Writer(str(d / f"{prefix}L_F0010000"), shapeType=shapefile.POLYLINE, encoding="cp949")
        w.field("구분", "C", 10)
        w.field("등고수치", "N", 10, 2)
        for k in range(-20, 21):
            w.line([[[x0 - 1200, y0 + 50 * k], [x0 + 1200, y0 + 50 * k]]])
            w.record("주곡선", 100 + 5 * k)
        w.close()
        stems.append(f"{prefix}L_F0010000")
    if spots:
        wp = shapefile.Writer(str(d / f"{prefix}P_F0020000"), shapeType=shapefile.POINT, encoding="cp949")
        wp.field("수치", "N", 10, 2)
        for dx, dy, v in spots:
            wp.point(x0 + dx, y0 + dy)
            wp.record(v)
        wp.close()
        stems.append(f"{prefix}P_F0020000")
    if buildings:
        wa = shapefile.Writer(str(d / f"{prefix}A_B0010000"), shapeType=shapefile.POLYGON, encoding="cp949")
        wa.field("명칭", "C", 50)
        wa.field("종류", "C", 20)
        wa.field("주기", "C", 100)
        wa.field("층수", "N", 5, 0)
        for k, (label, levels) in enumerate(buildings):
            cx = x0 + 200 * k
            wa.poly([[[cx - 20, y0 - 20], [cx - 20, y0 + 20], [cx + 20, y0 + 20], [cx + 20, y0 - 20], [cx - 20, y0 - 20]]])
            wa.record("서울대학교", "주택외건물", label, levels)
        wa.close()
        stems.append(f"{prefix}A_B0010000")
    for stem in stems:
        (d / f"{stem}.prj").write_text(wkt, encoding="utf-8")
    return tmp_path / "topo"


def test_dem_from_contours(dem, tmp_path):
    from rasterio.warp import transform as warp

    x0, y0 = dem.origin
    topo = _write_topo(tmp_path, x0, y0)
    # 1:1,000 도엽: 등고선은 무시하고 표고점만 검증에 쓴다 (평면보다 0.5 m 높게 적어 둠)
    _write_topo(tmp_path, x0, y0, sheet="376120571", prefix="N1", spots=((-100, -100, 100 - 10 + 0.5),),
                buildings=(("다른건물", 1),))
    campus = tmp_path / "campus.csv"
    campus.write_text(f"building,name,lat,lon\n301,시험관,{P_LAT},{P_LON}\n", encoding="utf-8")
    out, bout = tmp_path / "dem" / "topo_dem.tif", tmp_path / "topo_buildings.geojson"
    assert dfc.main(["--topo", str(topo), "--buildings", str(campus), "--extent", "campus", "--margin", "0.003",
                     "--res", "2", "-o", str(out), "--buildings-output", str(bout)]) == 0
    d = be.Dem([out])
    lons, lats = [P_LON, P_LON + 0.001], [P_LAT, P_LAT - 0.001]
    _, ys = warp("EPSG:4326", "EPSG:5186", lons, lats)
    assert np.allclose(d.sample(lons, lats), 100 + 0.1 * (np.asarray(ys) - y0), atol=0.05)  # 등고선 사이 선형
    feats = json.loads(bout.read_text(encoding="utf-8"))["features"]
    assert len(feats) == 1  # 1:5,000 건물만
    p = feats[0]["properties"]
    assert p["name"] == "공과대학301동시험관" and p["ref"] == "301" and p["kind"] == "주택외건물" and p["levels"] == "5"
    assert p["fid"] == "topo/37612018/0"
    proj = be.LocalProj()
    rows, _ = be.estimate(_one(), be.load_footprints(bout, proj), d, proj)
    r = rows[0]
    assert r["footprint"] == "topo/37612018/0" and r["footprint_match"] == "inside" and r["dem"] == "topo_dem.tif"
    assert r["footprint_name"] == "공과대학301동시험관" and "다름" not in r["note"]
    assert abs(float(r["first_floor_est_m"]) - 100.0) < 0.1 and 3.8 <= float(r["ground_span_m"]) <= 4.0


def test_dem_covers_whole_sheet_by_default(dem, tmp_path):
    """기본(--extent data)은 캠퍼스 좌표와 상관없이 받은 도엽 전체를 덮는다 (도로 그래프용)."""
    import rasterio
    from rasterio.transform import array_bounds

    x0, y0 = dem.origin
    topo = _write_topo(tmp_path, x0, y0)
    out = tmp_path / "dem" / "topo_dem.tif"
    assert dfc.main(["--topo", str(topo), "--buildings", str(tmp_path / "없음.csv"), "--res", "20", "-o", str(out),
                     "--buildings-output", str(tmp_path / "b.geojson")]) == 0
    with rasterio.open(out) as ds:
        west, south, east, north = array_bounds(ds.height, ds.width, ds.transform)
    # 등고선은 y0 ± 1000 m (맨 아래 0 m 선은 빈 값으로 빠져 y0 − 950 m부터)
    assert west <= x0 - 1190 and east >= x0 + 1190 and south <= y0 - 940 and north >= y0 + 990


def test_topo_scale_and_check_points(dem, tmp_path):
    from rasterio.transform import from_origin

    x0, y0 = dem.origin
    _write_topo(tmp_path, x0, y0, spots=())
    _write_topo(tmp_path, x0, y0, sheet="376120571", prefix="N1", spots=(), buildings=())
    layers, sheets = dfc.find_layers(tmp_path / "topo")
    assert {s["sheet"]: s["scale"] for s in sheets} == {"37612018": "5000", "376120571": "1000"}
    assert len(layers["5000"][dfc.CONTOUR]) == 1 and len(layers["1000"][dfc.CONTOUR]) == 1
    assert [dfc.dong_refs(s) for s in ("사범대학10-1동교육정보관", "105동유전자공학연구소동관", "관악학생생활관919-B동",
                                       "인문대학4동,신양인문학술정보관")] == [["10-1"], ["105"], [], ["4"]]
    arr = np.full((10, 10), 50.0, dtype="float32")  # 오차 검증: 칸 가운데 기준 보간
    chk = dfc.check_points(arr, from_origin(0, 10, 1, 1), np.array([[5.0, 5.0], [2.5, 7.5], [50.0, 50.0]]),
                           np.array([49.0, 50.5, 1.0]))
    assert chk["n"] == 2 and abs(chk["mae"] - 0.75) < 1e-6 and abs(chk["mean"] - 0.25) < 1e-6 and chk["max"] == 1.0


def test_finer_dem_is_used_first(dem, tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    x0, y0 = dem.origin
    coarse = tmp_path / "coarse.tif"
    with rasterio.open(coarse, "w", driver="GTiff", width=40, height=40, count=1, dtype="float32", crs="EPSG:5186",
                       transform=from_origin(x0 - 1800, y0 + 1800, 90, 90), nodata=-9999) as ds:
        ds.write(np.full((40, 40), 50.0, dtype="float32"), 1)
    d = be.Dem([coarse, dem.src_path])  # 90 m를 먼저 줘도 5 m가 먼저 쓰인다
    assert [L.name for L in d.layers] == ["plane.tif", "coarse.tif"]
    assert abs(d.sample([P_LON], [P_LAT])[0] - 100.0) < 1e-3 and d.source_at(P_LON, P_LAT) == "plane.tif"


def test_topo_building_ids_are_unique_per_sheet(tmp_path):
    shapefile = pytest.importorskip("shapefile")
    paths = []
    for sheet in ("376120571", "376120572"):  # 1:1,000 도엽번호는 9자리
        d = tmp_path / sheet
        d.mkdir()
        w = shapefile.Writer(str(d / "N1A_B0010000"), shapeType=shapefile.POLYGON, encoding="cp949")
        w.field("명칭", "C", 50)
        w.poly([[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]])
        w.record("건물")
        w.close()
        paths.append(d / "N1A_B0010000.shp")
    feats = dfc.read_buildings(paths, "EPSG:5186")
    assert [f["properties"]["fid"] for f in feats] == ["topo/376120571/0", "topo/376120572/0"]


def _topo_fp(proj, fid, pts, name="", ref=""):
    ring = _lonlat(proj, pts + pts[:1])
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"fid": fid, "name": name, "ref": ref}}


def test_split_pieces_are_merged(dem, tmp_path):
    """도엽 경계(x = 0)에서 잘린 40×20 m 건물 → 한 윤곽. 같은 도엽 안에서 벽을 맞댄 건물은 합치지 않는다."""
    proj = be.LocalProj()
    px, py = (float(v) for v in proj.fwd(P_LON, P_LAT))
    feats = [
        _topo_fp(proj, "topo/37612018/1", [(px - 20, py - 10), (px, py - 10), (px, py + 10), (px - 20, py + 10)], "공학관", "301"),
        _topo_fp(proj, "topo/37612019/7", [(px, py - 10), (px + 20, py - 10), (px + 20, py + 10), (px, py + 10)]),
        _topo_fp(proj, "topo/37612019/8", [(px + 20, py - 10), (px + 40, py - 10), (px + 40, py + 10), (px + 20, py + 10)]),
    ]
    fps, n = be.merge_split_pieces(be.load_footprints(_geojson(tmp_path, "t.geojson", feats), proj))
    assert n == 1 and len(fps) == 2
    m = next(fp for fp in fps if "+" in fp.fid)
    assert m.fid == "topo/37612018/1+topo/37612019/7" and m.props["name"] == "공학관" and be.refs_of(m) == {"301"}
    segs = m.boundary()
    assert abs(float(np.hypot(*(segs[:, 1] - segs[:, 0]).T).sum()) - 120.0) < 0.5  # 둘레 2×(40+20), 잘린 선 제외
    assert m.contains(px - 10, py) and m.contains(px + 10, py) and not m.contains(px + 30, py)
    rows, _ = be.estimate(_one(), fps, dem, proj, step=1.0)
    r = rows[0]
    assert r["footprint"] == m.fid and r["perimeter_m"] == "120"
    assert abs(float(r["first_floor_est_m"]) - float(_truth(dem, [P_LON], [P_LAT])[0])) <= 0.1  # 합친 윤곽의 가운데


def test_topo_label_matching(tmp_path):
    proj = be.LocalProj()
    sq = lambda cx, cy, h: [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]  # noqa: E731
    fps = be.load_footprints(_geojson(tmp_path, "t.geojson", [
        _topo_fp(proj, "topo/1/0", sq(0, 0, 10), "음악대학49동예술관", "49"),
        _topo_fp(proj, "topo/1/1", sq(25, 0, 3), "미술대학49-1동", "49-1"),
        _topo_fp(proj, "topo/1/2", sq(0, 60, 10), "경영대학59동", "59"),
        _topo_fp(proj, "topo/1/3", sq(0, 120, 10), "137동언어교육원", "137"),
    ]), proj)
    # 좌표가 어느 윤곽에도 없음: 가장 가까운 49-1동(2 m) 대신 동 번호가 맞는 49동(10 m)
    fp, how = be.match_footprint("49", 20, 0, fps, ref_first=False)
    assert fp.fid == "topo/1/0" and how == "ref"
    fp, how, _ = be.pick_footprints("59-1", 0, 60, fps, [])  # 59-1동이 '59동' 윤곽 안 → 같은 건물로 봄
    assert fp.fid == "topo/1/2" and how == "inside" and not be.number_conflict("59-1", be.refs_of(fp))
    assert be.number_conflict("500", {"503"}) and not be.number_conflict("10-1", {"10"})
    assert be.match_footprint("117", 0, 135, fps, ref_first=False) == (None, "none")  # 137동 윤곽은 다른 건물


def test_topo_outline_with_osm_entrances(dem, tmp_path):
    """둘레는 수치지형도 윤곽으로 재고, 출입구는 같은 건물의 OSM 윤곽(보행로와 노드 공유)에서 가져온다."""
    proj = be.LocalProj()
    px, py = (float(v) for v in proj.fwd(P_LON, P_LAT))
    topo = _topo_fp(proj, "topo/37612018/0", [(px - 20, py - 20), (px + 20, py - 20), (px + 20, py + 20), (px - 20, py + 20)],
                    "공과대학301동", "301")
    osm = _poly(_lonlat(proj, [(px - 18, py - 19), (px + 20, py - 19), (px + 20, py + 19), (px - 18, py + 19), (px - 18, py - 19)]),
                {"osm_type": "way", "osm_id": 7, "nodes": [1, 2, 3, 4, 1]})
    fps = be.load_footprints(_geojson(tmp_path, "fp.geojson", [topo, osm]), proj)
    path = _geojson(tmp_path, "paths.geojson", [{
        "type": "Feature", "geometry": {"type": "LineString", "coordinates": _lonlat(proj, [(px + 50, py - 19), (px + 20, py - 19)])},
        "properties": {"osm_id": 30, "highway": "footway", "nodes": [99, 2]}}])
    rows, ents = be.estimate(_one(), fps, dem, proj, paths=be.load_paths(path, proj))
    assert rows[0]["footprint"] == "topo/37612018/0" and rows[0]["footprint_match"] == "inside"
    assert [e["source"] for e in ents] == ["osm-path-join"] and rows[0]["entrances"] == "1"
    # 좌표를 품은 수치지형도 윤곽에 다른 번호(503)가 적혀 있고 OSM ref가 500이면 OSM 윤곽
    both = be.load_footprints(_geojson(tmp_path, "w.geojson", [
        _topo_fp(proj, "topo/1/0", [(-10, -10), (10, -10), (10, 10), (-10, 10)], "자연과학대학503동", "503"),
        _poly(_lonlat(proj, [(15, -10), (35, -10), (35, 10), (15, 10), (15, -10)]), {"osm_type": "way", "osm_id": 8, "ref": "500"}),
    ]), proj)
    fp, how, _ = be.pick_footprints("500", 0, 0, [f for f in both if f.fid.startswith("topo/")],
                                    [f for f in both if not f.fid.startswith("topo/")])
    assert fp.fid == "osm-way/8" and how == "ref"
