"""캠퍼스 바탕 지도 자료(data/basemap.json)를 만든다. 앱·웹이 지도 타일을 받는 대신 이 파일 하나로 지도를 직접 그린다.

  python scripts/basemap.py            # data/topo(수치지형도) + data/osm_*.geojson → data/basemap.json
  python scripts/basemap.py --dry-run  # 크기만 찍고 파일은 쓰지 않는다

입력
  data/topo/<도엽 폴더>/   수치지형도 1:5,000(도엽번호 8자리) SHP. 관악캠퍼스 둘레 네 장(37612018·019·028·029)
      원본은 저장소에 없다(국외 반출 금지 자료). 국토정보플랫폼에서 받아 PC 에 둔다: docs/topo.md
      N3A_A0010000 도로경계(면)   N3A_A0033320 인도   N3A_B0010000 건물   N3L_F0010000 등고선
      N3A_E0010001 하천경계   N3A_E0032111 실폭하천   N3A_E0052114 호수·저수지
  data/osm_basemap.geojson  숲·잔디·공원(면)과 길(선), 자료 범위 전체. fetch_osm_basemap.py(인터넷 되는 PC)가 만든다
  data/osm_paths.geojson    osm_basemap 이 없을 때 쓰는 캠퍼스 둘레 길(fetch_osm_footprints.py)
  data/campus_buildings.csv 캠퍼스 건물 좌표 → 캠퍼스 땅(어림 경계)
출력
  data/basemap.json         형식·그리는 법은 docs/basemap.md. export_web.py 가 web/data/ 로 복사한다

- 범위(bounds)는 도엽 네 장 전체(약 4.4 × 5.6 km). 지도는 이 범위 밖을 보여 주면 안 된다(빈 땅). docs/basemap.md 의 최소 배율 규칙
- 캠퍼스 땅에서 400 m 안은 자세히(건물 0.2 m·좌표 소수 6자리, 등고선 1.2 m), 그 밖은 간단히(건물은 2.4 m 안쪽 틈을
  메운 덩어리 1 m·소수 5자리, 등고선 5 m) 줄인다. 멀리는 작게 보는 곳이라
- 초록(숲·잔디)은 osm_basemap 의 면을 쓴다. 그 파일이 없으면 '캠퍼스·건물 둘레·도로·물이 아닌 땅'으로 어림한다(green_approx: true)
- 출처: 국토지리정보원 수치지형도(공공누리 제1유형, 출처 표시), © OpenStreetMap contributors(ODbL). OSM 에서 온 층(길·초록)은
  이 파일과 함께 ODbL 로 공개된다(레포가 공개라 따로 할 일은 없다)
- 필요한 패키지: pyshp, shapely, pyproj (requirements.txt)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TOPO = DATA / "topo"
OUT = DATA / "basemap.json"
OSM_BASEMAP = DATA / "osm_basemap.geojson"
OSM_PATHS = DATA / "osm_paths.geojson"
CAMPUS = DATA / "campus_buildings.csv"

SHEET_5000 = re.compile(r"_(\d{8})_")  # 도엽번호 8자리 = 1:5,000 (9자리는 1:1,000)
WATER = ("N3A_E0010001", "N3A_E0032111", "N3A_E0052114")
ROAD, WALK, BUILDING, CONTOUR = "N3A_A0010000", "N3A_A0033320", "N3A_B0010000", "N3L_F0010000"
SRC = ["국토지리정보원 수치지형도(1:5,000, 2025) · 공공누리 제1유형", "© OpenStreetMap contributors (ODbL)"]

NEAR_M = 400  # 캠퍼스 땅에서 이 거리 안은 자세히
MAJOR = {"motorway": 0, "motorway_link": 0, "trunk": 0, "trunk_link": 0, "primary": 1, "primary_link": 1,
         "secondary": 2, "secondary_link": 2}
ROAD_CLASS = {0: "road_trunk", 1: "road_primary", 2: "road_secondary"}
MINOR_ROAD = {"tertiary", "tertiary_link", "unclassified", "residential", "service", "living_street"}
WALKWAY = {"footway", "path", "track", "cycleway", "bridleway"}
GREEN_KIND = {  # OSM 태그 → 층
    ("landuse", "forest"): "green", ("natural", "wood"): "green", ("natural", "scrub"): "green",
    ("leisure", "nature_reserve"): "green", ("leisure", "park"): "park", ("leisure", "garden"): "park",
    ("landuse", "grass"): "grass", ("landuse", "meadow"): "grass", ("landuse", "village_green"): "grass",
    ("landuse", "recreation_ground"): "grass", ("natural", "grassland"): "grass", ("natural", "heath"): "grass",
    ("leisure", "pitch"): "pitch", ("leisure", "track"): "pitch", ("leisure", "golf_course"): "grass",
}


# ---------------------------------------------------------------- 좌표 부호화 (Google polyline)

def _enc_num(v: int) -> str:
    v = ~(v << 1) if v < 0 else v << 1
    out = []
    while v >= 0x20:
        out.append(chr((0x20 | (v & 0x1F)) + 63))
        v >>= 5
    out.append(chr(v + 63))
    return "".join(out)


def encode_latlon(latlon, prec: int) -> str:
    """[(lat, lon), ...] → polyline 문자열. 소수 prec 자리(6 = 약 0.1 m, 5 = 약 1 m). 같은 점이 이어지면 하나로."""
    f = 10 ** prec
    out, plat, plon, first = [], 0, 0, True
    for lat, lon in latlon:
        ilat, ilon = round(lat * f), round(lon * f)
        if not first and ilat == plat and ilon == plon:
            continue
        out.append(_enc_num(ilat - plat) + _enc_num(ilon - plon))
        plat, plon, first = ilat, ilon, False
    return "".join(out)


def decode(text: str, prec: int) -> list[tuple[float, float]]:
    """polyline → [(lat, lon), ...] (테스트·점검용. 화면의 decodePolyline 과 같은 방식)."""
    out, i, lat, lon, f = [], 0, 0, 0, 10 ** prec
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
        out.append((lat / f, lon / f))
    return out


# ---------------------------------------------------------------- 읽기

class Proj:
    """EPSG:5186(수치지형도, m) ↔ 경위도."""

    def __init__(self):
        from pyproj import Transformer
        self.to_ll = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)
        self.to_tm = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)

    def latlon(self, coords) -> list[tuple[float, float]]:
        xs, ys = zip(*[(c[0], c[1]) for c in coords])
        lon, lat = self.to_ll.transform(xs, ys)
        return list(zip(lat, lon))

    def tm(self, lon, lat):
        return self.to_tm.transform(lon, lat)


def sheet_dirs(topo: Path) -> list[Path]:
    return sorted(p for p in topo.iterdir() if p.is_dir() and SHEET_5000.search(p.name)) if topo.exists() else []


def read_layer(dirs: list[Path], layer: str):
    import shapefile
    from shapely.geometry import shape

    for d in dirs:
        p = d / f"{layer}.shp"
        if not p.exists():
            continue
        with warnings.catch_warnings():  # .cpg 의 'EUC-KR' 과 cp949 가 다르다는 경고(cp949 가 EUC-KR 을 포함)
            warnings.simplefilter("ignore")
            r = shapefile.Reader(str(p), encoding="cp949", encodingErrors="replace")
            names = [f[0] for f in r.fields[1:]]
            for sr in r.iterShapeRecords():
                if sr.shape.points:
                    g = shape(sr.shape.__geo_interface__)
                    yield (g if g.is_valid else g.buffer(0)), dict(zip(names, sr.record))


def layer_bbox(dirs: list[Path], layer: str):
    import shapefile

    bb = None
    for d in dirs:
        p = d / f"{layer}.shp"
        if p.exists():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                b = shapefile.Reader(str(p), encoding="cp949", encodingErrors="replace").bbox
            bb = list(b) if bb is None else [min(bb[0], b[0]), min(bb[1], b[1]), max(bb[2], b[2]), max(bb[3], b[3])]
    return bb


def read_geojson(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("features", [])


def campus_points(path: Path) -> list[tuple[float, float]]:
    pts = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("lat") and r.get("lon"):
                pts.append((float(r["lon"]), float(r["lat"])))
    return pts


# ---------------------------------------------------------------- 도형

def polys(g):
    from shapely.geometry import Polygon

    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [x for x in getattr(g, "geoms", []) if isinstance(x, Polygon)]


def lines(g):
    from shapely.geometry import LineString

    if g.is_empty:
        return []
    if isinstance(g, LineString):
        return [g]
    out = []
    for x in getattr(g, "geoms", []):
        out.extend(lines(x))
    return out


class Builder:
    def __init__(self, proj: Proj, clip, near):
        self.proj, self.clip, self.near = proj, clip, near

    def areas(self, geoms, tol_near, tol_far=None, min_area=1.0, merge=True, split=True):
        """면 → [[소수 자리, 바깥 고리, 구멍...], ...]. 캠퍼스 가까이는 tol_near·소수 6자리, 멀리는 tol_far·소수 5자리.
        split=False 면 전부 가까운 쪽으로(색이 하나인 큰 면은 쪼개면 경계선이 보여서)."""
        from shapely.ops import unary_union

        tol_far = tol_near if tol_far is None else tol_far
        geoms = [g.intersection(self.clip) for g in geoms if g.intersects(self.clip)]
        if merge and geoms:
            geoms = polys(unary_union(geoms))
        out = []
        for g in geoms:
            for p in polys(g):
                far = split and not p.intersects(self.near)
                tol, prec, amin = (tol_far, 5, min_area * 2) if far else (tol_near, 6, min_area)
                for q in polys(p.simplify(tol, preserve_topology=True)):
                    if q.area < amin:
                        continue
                    item = [prec, encode_latlon(self.proj.latlon(q.exterior.coords), prec)]
                    item += [encode_latlon(self.proj.latlon(r.coords), prec) for r in q.interiors if abs(_ring_area(r.coords)) >= amin]
                    out.append(item)
        return out

    def line_items(self, items, tol=0.4, min_len=3.0, within=None):
        """[(종류, 선), ...] → [[종류, polyline(소수 5자리)], ...]. within 을 주면 그 안만."""
        out = []
        area = self.clip if within is None else self.clip.intersection(within)
        for kind, g in items:
            for l in lines(g.intersection(area)):
                l = l.simplify(tol)
                if l.length >= min_len:
                    out.append([kind, encode_latlon(self.proj.latlon(l.coords), 5)])
        return out


def _ring_area(coords) -> float:
    c = list(coords)
    return 0.5 * sum(c[i][0] * c[i + 1][1] - c[i + 1][0] * c[i][1] for i in range(len(c) - 1))


def osm_tm(proj: Proj, feature):
    from shapely.geometry import shape
    from shapely.ops import transform

    g = shape(feature["geometry"])
    g = transform(lambda x, y, z=None: proj.tm(x, y), g)
    return g if g.is_valid else g.buffer(0)


# ---------------------------------------------------------------- 만들기

def build(topo: Path = TOPO, osm_basemap: Path = OSM_BASEMAP, osm_paths: Path = OSM_PATHS, campus: Path = CAMPUS) -> dict:
    from shapely.geometry import Point, box
    from shapely.ops import linemerge, unary_union
    from shapely.strtree import STRtree

    proj = Proj()
    dirs = sheet_dirs(topo)
    if not dirs:
        raise SystemExit(f"{topo} 에 1:5,000 도엽 폴더가 없다(수치지형도 원본은 저장소에 없다. 받는 법: docs/topo.md)")
    bb = layer_bbox(dirs, CONTOUR) or layer_bbox(dirs, BUILDING)
    clip = box(bb[0] + 5, bb[1] + 5, bb[2] - 5, bb[3] - 5)  # 도엽 가장자리 5 m 는 자른다(조각난 선)

    pts = [proj.tm(lon, lat) for lon, lat in campus_points(campus)]
    pts = [p for p in pts if clip.contains(Point(p))]
    camp = unary_union([Point(x, y).buffer(110, 16) for x, y in pts]).buffer(60).buffer(-90).simplify(4)
    near = camp.buffer(NEAR_M)
    B = Builder(proj, clip, near)

    osm = read_geojson(osm_basemap)
    osm_lines = [f for f in (osm or []) if f["geometry"]["type"] in ("LineString", "MultiLineString")]
    osm_areas = [f for f in (osm or []) if f["geometry"]["type"] in ("Polygon", "MultiPolygon")]
    if not osm_lines:
        osm_lines = [f for f in (read_geojson(osm_paths) or []) if f["geometry"]["type"] in ("LineString", "MultiLineString")]

    # 길(OSM 선): 큰길은 도로면 색을 정하는 데만 쓰고, 나머지는 선으로 그린다. 실내·지하·층이 있는 길은 뺀다
    major, line_kinds = [], {"road": [], "pedestrian": [], "walk": [], "steps": []}
    for f in osm_lines:
        pr = f["properties"]
        hw = pr.get("highway")
        if pr.get("indoor") in ("yes", "room", "corridor") or pr.get("tunnel") in ("yes", "building_passage", "culvert") \
                or str(pr.get("level") or "0") not in ("0", ""):
            continue
        g = osm_tm(proj, f)
        if hw in MAJOR:
            major.append((MAJOR[hw], g))
        elif hw in MINOR_ROAD:
            line_kinds["road"].append((hw, g))
        elif hw == "pedestrian":
            line_kinds["pedestrian"].append((hw, g))
        elif hw in WALKWAY:
            line_kinds["walk"].append((hw, g))
        elif hw == "steps":
            line_kinds["steps"].append((hw, g))

    data: dict = {"v": 1, "built": dt.date.today().isoformat(), "src": SRC}
    lo, la = proj.to_ll.transform(clip.bounds[0], clip.bounds[1])
    hlo, hla = proj.to_ll.transform(clip.bounds[2], clip.bounds[3])
    # 범위는 안쪽으로 반올림(지도는 이 안만 보여 준다)
    data["bounds"] = [_ceil(la), _ceil(lo), _floor(hla), _floor(hlo)]
    area: dict = {}

    water = [g for L in WATER for g, _ in read_layer(dirs, L)]
    roads = [g for g, _ in read_layer(dirs, ROAD) if g.intersects(clip)]
    walks = [g for g, _ in read_layer(dirs, WALK)]
    bld = [g for g, _ in read_layer(dirs, BUILDING) if g.intersects(clip)]

    # 초록: OSM 면이 있으면 그것, 없으면 어림
    greens = {"green": [], "park": [], "grass": [], "pitch": []}
    for f in osm_areas:
        pr = f["properties"]
        kind = pr.get("kind") or next((GREEN_KIND[k] for k in GREEN_KIND if pr.get(k[0]) == k[1]), None)
        if kind in greens:
            greens[kind].append(osm_tm(proj, f))
    data["green_approx"] = not any(greens.values())
    if data["green_approx"]:
        built = unary_union([g.buffer(22, 4) for g in bld] + [g.buffer(6, 4) for g in roads] + water + [camp])
        greens["green"] = [clip.difference(built).buffer(-10).buffer(10)]
    area["green"] = B.areas(greens["green"], 3, 4, min_area=2000, split=False)
    for k in ("park", "grass", "pitch"):
        if greens[k]:
            area[k] = B.areas(greens[k], 1, 2, min_area=50, split=False)
    area["campus"] = B.areas([camp], 2, min_area=100, merge=False, split=False)
    area["water"] = B.areas(water, 0.5, 1.0, min_area=4)
    area["walk"] = B.areas(walks, 0.35, 0.8, min_area=1, split=False)

    # 도로면: 큰길(OSM 선 ± 12 m)과 면적 45 % 넘게 겹치면 그 등급 색, 아니면 흰 길
    bufs = [g.buffer(12) for _, g in major]
    tree = STRtree(bufs) if bufs else None
    by_class: dict[str, list] = {"road": [], **{v: [] for v in ROAD_CLASS.values()}}
    for poly in roads:
        best = None
        if tree is not None:
            for i in tree.query(poly):
                if poly.intersection(bufs[i]).area > 0.45 * poly.area:
                    best = major[i][0] if best is None else min(best, major[i][0])
        by_class[ROAD_CLASS[best] if best is not None else "road"].append(poly)
    for k, v in by_class.items():
        if v:
            area[k] = B.areas(v, 0.5, min_area=2, split=False)  # 큰 면이 가까이·멀리 걸쳐 있어 쪼개지 않는다(쪼개면 테두리 선이 보인다)

    # 건물: 캠퍼스 가까이는 한 채씩 자세히. 멀리(주택가)는 2 m 안쪽 틈을 메워 덩어리로 줄인다(멀리서 보는 곳이라)
    near_b = [g for g in bld if g.intersects(near)]
    far_b = unary_union([g for g in bld if not g.intersects(near)]).buffer(1.2, 2).buffer(-1.2, 2)
    area["building"] = B.areas(near_b, 0.2, min_area=6, split=False) + B.areas(polys(far_b), 1.0, 1.0, min_area=8, merge=False)
    data["area"] = area

    # 캠퍼스 안 찻길은 수치지형도 도로면에 없어서 OSM 선으로 그린다. 캠퍼스에서 먼 동네 길은 도로면이 있으니 선은 뺀다
    data["line"] = {k: B.line_items(v, within=near if k == "road" else None) for k, v in line_kinds.items() if v}

    # 등고선: 5 m 주곡선, 25 m 계곡선. 도엽 경계에서 잘린 조각은 잇는다. 캠퍼스에서 멀면 더 간단히
    cont: dict[tuple[str, int], list] = {}
    for g, a in read_layer(dirs, CONTOUR):
        if g.intersects(clip):
            key = ("index" if a.get("구분") == "계곡선" else "minor", int(round(float(a.get("등고수치") or 0))))
            cont.setdefault(key, []).extend(lines(g.intersection(clip)))
    contour: dict = {"minor": [], "index": []}
    for (kind, z), ls in sorted(cont.items()):
        merged = linemerge(ls) if len(ls) > 1 else ls[0]
        for l in lines(merged):
            for part, tol in ((l.intersection(near), 1.2), (l.difference(near), 5.0)):
                for seg in lines(part):
                    seg = seg.simplify(tol)
                    if seg.length >= 8:
                        contour[kind].append([z, encode_latlon(proj.latlon(seg.coords), 5)])
    data["contour"] = contour
    return data


def _ceil(v: float) -> float:
    import math
    return math.ceil(v * 1e5) / 1e5


def _floor(v: float) -> float:
    import math
    return math.floor(v * 1e5) / 1e5


def sizes(data: dict) -> list[tuple[str, int, float]]:
    def kb(v):
        return len(json.dumps(v, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) / 1024

    rows = [(f"area.{k}", len(v), kb(v)) for k, v in data["area"].items()]
    rows += [(f"line.{k}", len(v), kb(v)) for k, v in data["line"].items()]
    rows += [(f"contour.{k}", len(v), kb(v)) for k, v in data["contour"].items()]
    return rows


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--topo", type=Path, default=TOPO)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    data = build(args.topo)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    s, w, n, e = data["bounds"]
    print(f"범위 남 {s} 서 {w} 북 {n} 동 {e} · 초록 {'어림' if data['green_approx'] else 'OSM'}")
    for name, count, kb in sizes(data):
        print(f"  {name:22s} {count:5d}  {kb:7.1f} KB")
    print(f"합계 {len(raw) / 1024:.1f} KB (gzip {len(gzip.compress(raw, 9)) / 1024:.1f} KB)")
    if not args.dry_run:
        args.out.write_bytes(raw)
        print(f"저장: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
