"""건물별 1층·로비층·출입구 고도 추정 — '캠퍼스 마법 지도' 개발자 전달용.

  python scripts/building_elevation.py                          # data/dem 폴더의 .img/.tif 전부
  python scripts/building_elevation.py --dem 경로1.img 경로2.img
  python scripts/building_elevation.py --dem-crs EPSG:5186      # DEM 파일에 좌표계 정보가 없을 때만

입력
  건물 목록    data/campus_buildings.csv (fetch_campus_buildings.py) + data/buildings.csv 의 수동 항목(GATE 등)
  건물 윤곽    data/topo_buildings.geojson  수치지형도 (dem_from_contours.py). 도엽 경계에서 잘린 조각은 합친다
               data/osm_buildings.geojson   ┐
  출입구 노드  data/osm_entrances.geojson   │ fetch_osm_footprints.py. 없으면 그 부분만 건너뛴다
  보행로       data/osm_paths.geojson       ┘
  수동 출입구  data/entrances_manual.csv (선택) — building,lat,lon,floor,kind,note
               적힌 건물은 자동 후보 대신 이것만 쓴다. 현장에서 확인한 층(floor)을 적으면 추정값과 나란히 나온다
  DEM          data/dem 의 .img/.tif 전부. 수치지형도로 만든 DEM(dem_from_contours.py), 공개 DEM(90 m) 등.
               건물·나무를 뺀 '지면' 고도여야 한다. SRTM 같은 표면 고도는 건물 높이가 섞여 쓸 수 없다

방법
  윤곽        캠퍼스맵 좌표를 품은 수치지형도 윤곽 → 주기에 같은 동 번호가 적힌 수치지형도 윤곽(80 m 이내)
              → OSM 윤곽(ref가 동 번호와 같거나 좌표를 품음) → 20 m 이내 윤곽. 도엽 경계에서 잘린 조각은 합친다.
              출입구 후보는 그 윤곽과, 같은 건물의 OSM 윤곽(보행로와 노드를 공유) 양쪽에서 모은다.
  1층 기준면  건물 둘레를 --step m(기본 2) 간격으로 따라가며 DEM을 쌍선형 보간으로 읽고, 둘레 길이로 가중평균한다.
              건축법 시행령 제119조가 지하층을 판단할 때 쓰는 지표면(건물 주위가 접하는 지표면 높이를
              수평거리로 가중평균한 높이)과 같은 정의라, 1층 바닥은 이 높이에서 층고의 절반 이내에 있다.
  출입구      지상에서 들어가는 문이 여러 개이고 높이가 다를 수 있어 출입구마다 따로 잰다. 후보는
              ① OSM entrance 태그 노드(윤곽에 속하거나 경계 3 m 이내) ② 보행로가 윤곽과 노드를 공유하는 점
              ③ 보행로 끝점이 경계 2.5 m 이내면 가장 가까운 경계점. 다리·터널·실내 통로는 지상 출입이 아니라 뺀다.
              6 m 안의 후보는 하나로 합친다.
              출입구 층 추정 = 1층 + round((출입구 지면 고도 − 1층 기준면) ÷ 층고), 층고 기본 4 m. ±1층 틀릴 수 있다.
  로비층      main 출입구가 있으면 그 고도. 없으면 출입구들 높이 차가 1.5 m 미만일 때 그 평균.
              출입구 정보가 없는 평지 건물은 1층 기준면. 그 밖(여러 높이)은 비워 두고 '확정 필요'로 표시.

출력
  data/buildings_elevation.csv / .geojson   건물별
  data/building_entrances.csv / .geojson    출입구별
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CAMPUS = DATA / "campus_buildings.csv"
BUILDINGS = DATA / "buildings.csv"
HISTORY = DATA / "buildings_history.csv"
FOOTPRINTS = DATA / "osm_buildings.geojson"
TOPO_FOOTPRINTS = DATA / "topo_buildings.geojson"  # dem_from_contours.py
ENTRANCES = DATA / "osm_entrances.geojson"
PATHS = DATA / "osm_paths.geojson"
MANUAL = DATA / "entrances_manual.csv"
DEM_DIR = DATA / "dem"
OUT_CSV = DATA / "buildings_elevation.csv"
OUT_ENT = DATA / "building_entrances.csv"
DEM_EXT = {".img", ".tif", ".tiff"}

FIELDS = ["building", "name", "lat", "lon", "first_floor_est_m", "lobby_est_m", "lobby_source",
          "entrances", "entrance_floors", "multi_level_access", "entrance_min_m", "entrance_max_m",
          "ground_min_m", "ground_max_m", "ground_span_m", "slope_site", "point_ground_m",
          "footprint", "footprint_name", "footprint_match", "perimeter_m", "samples", "dem", "lecture_building", "note"]
ENT_FIELDS = ["building", "name", "entrance_no", "lat", "lon", "ground_m", "rel_to_1f_m", "floor_est",
              "floor_checked", "kind", "source", "osm_id", "osm_level", "note"]

WALK = {"footway", "path", "steps", "pedestrian", "service", "living_street", "residential", "unclassified",
        "tertiary", "secondary", "primary", "track", "cycleway", "road"}
SOURCE_RANK = {"manual": 0, "osm-entrance": 1, "osm-path-join": 2, "osm-path-end": 3}


# ---------------------------------------------------------------- 좌표

class LocalProj:
    """캠퍼스 안(수 km)에서만 쓰는 평면 근사. 경위도 ↔ m (동쪽 x, 북쪽 y)."""

    def __init__(self, lat0: float = 37.4590, lon0: float = 126.9520):
        phi = math.radians(lat0)
        self.lat0, self.lon0 = lat0, lon0
        self.mlat = 111132.954 - 559.822 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
        self.mlon = 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi) + 0.118 * math.cos(5 * phi)

    def fwd(self, lon, lat):
        return (np.asarray(lon, float) - self.lon0) * self.mlon, (np.asarray(lat, float) - self.lat0) * self.mlat

    def inv(self, x, y):
        return self.lon0 + np.asarray(x, float) / self.mlon, self.lat0 + np.asarray(y, float) / self.mlat


# ---------------------------------------------------------------- DEM

def bilinear(arr: np.ndarray, transform, xs, ys) -> np.ndarray:
    """격자 중심 기준 쌍선형 보간. 가장자리 반 칸이나 이웃이 빈 칸이면 그 점이 속한 칸 값을 쓴다."""
    inv = ~transform  # (x, y) → (열, 행). affine 버전과 무관하게 계수로 직접 계산
    xs, ys = np.atleast_1d(np.asarray(xs, float)), np.atleast_1d(np.asarray(ys, float))
    cols = inv.a * xs + inv.b * ys + inv.c
    rows = inv.d * xs + inv.e * ys + inv.f
    c, r = cols - 0.5, rows - 0.5
    h, w = arr.shape
    j0, i0 = np.floor(c).astype(int), np.floor(r).astype(int)
    fc, fr = c - j0, r - i0
    out = np.full(c.shape, np.nan)
    inside = (i0 >= 0) & (j0 >= 0) & (i0 + 1 < h) & (j0 + 1 < w)
    if inside.any():
        a, b, u, v = i0[inside], j0[inside], fr[inside], fc[inside]
        out[inside] = (arr[a, b] * (1 - u) * (1 - v) + arr[a, b + 1] * (1 - u) * v
                       + arr[a + 1, b] * u * (1 - v) + arr[a + 1, b + 1] * u * v)
    need = np.isnan(out)
    if need.any():
        ri, ci = np.floor(rows[need]).astype(int), np.floor(cols[need]).astype(int)
        ok = (ri >= 0) & (ci >= 0) & (ri < h) & (ci < w)
        vals = np.full(ri.shape, np.nan)
        vals[ok] = arr[ri[ok], ci[ok]]
        out[need] = vals
    return out


@dataclass
class DemLayer:
    name: str
    crs: object
    transform: object
    arr: np.ndarray
    res: tuple[float, float]
    full_size: tuple[int, int] = (0, 0)  # 파일 전체 (가로, 세로) 칸 수

    def bounds_wgs84(self) -> tuple[float, float, float, float]:
        from rasterio.transform import array_bounds
        from rasterio.warp import transform_bounds
        h, w = self.arr.shape
        west, south, east, north = array_bounds(h, w, self.transform)
        return transform_bounds(self.crs, "EPSG:4326", west, south, east, north)


class Dem:
    """DEM 파일 여러 장(도엽)을 겹쳐 쓴다. 한 점은 값이 있는 첫 도엽에서 읽는다.
    bbox(남, 서, 북, 동 경위도)를 주면 그 범위만 읽는다. 1 m 격자 도엽처럼 큰 파일도 캠퍼스 부분만 메모리에 올린다."""

    def __init__(self, paths: list[Path], crs_override: str | None = None,
                 bbox: tuple[float, float, float, float] | None = None):
        import rasterio
        from rasterio.crs import CRS
        from rasterio.warp import transform_bounds
        from rasterio.windows import Window

        self.layers: list[DemLayer] = []
        self.skipped: list[str] = []
        for p in paths:
            with rasterio.open(p) as ds:
                crs = CRS.from_user_input(crs_override) if crs_override else ds.crs
                if crs is None:
                    raise SystemExit(f"{p.name}: 좌표계 정보가 없음 → --dem-crs EPSG:5186 처럼 지정")
                window = None
                if bbox is not None:
                    s, w, n, e = bbox
                    left, bottom, right, top = transform_bounds("EPSG:4326", crs, w, s, e, n)
                    inv = ~ds.transform
                    cs = [inv.a * x + inv.b * y + inv.c for x in (left, right) for y in (bottom, top)]
                    rs = [inv.d * x + inv.e * y + inv.f for x in (left, right) for y in (bottom, top)]
                    c0, c1 = max(0, math.floor(min(cs)) - 2), min(ds.width, math.ceil(max(cs)) + 2)
                    r0, r1 = max(0, math.floor(min(rs)) - 2), min(ds.height, math.ceil(max(rs)) + 2)
                    if c0 >= c1 or r0 >= r1:  # 캠퍼스와 겹치지 않는 도엽
                        self.skipped.append(p.name)
                        continue
                    window = Window(c0, r0, c1 - c0, r1 - r0)
                arr = ds.read(1, window=window, masked=True).astype("float32").filled(np.nan)
                with np.errstate(invalid="ignore"):
                    arr[(arr < -100) | (arr > 3000)] = np.nan  # nodata 표시가 없는 -9999 같은 값
                transform = ds.window_transform(window) if window is not None else ds.transform
                self.layers.append(DemLayer(p.name, crs, transform, arr, tuple(ds.res), (ds.width, ds.height)))
        self.layers.sort(key=lambda L: abs(L.res[0] * L.res[1]))  # 촘촘한 DEM(수치지형도 2 m)을 90 m보다 먼저

    def source_at(self, lon: float, lat: float) -> str:
        """이 점의 값을 준 DEM 이름."""
        from rasterio.warp import transform as warp

        for layer in self.layers:
            xs, ys = warp("EPSG:4326", layer.crs, [lon], [lat])
            if not np.isnan(bilinear(layer.arr, layer.transform, xs, ys)[0]):
                return layer.name
        return ""

    def sample(self, lons, lats) -> np.ndarray:
        from rasterio.warp import transform as warp

        lons = np.atleast_1d(np.asarray(lons, float))
        lats = np.atleast_1d(np.asarray(lats, float))
        out = np.full(lons.shape, np.nan)
        for layer in self.layers:
            need = np.isnan(out)
            if not need.any():
                break
            xs, ys = warp("EPSG:4326", layer.crs, lons[need].tolist(), lats[need].tolist())
            out[need] = bilinear(layer.arr, layer.transform, xs, ys)
        return out


def dem_paths(args_dem: list[str]) -> list[Path]:
    paths: list[Path] = []
    for a in args_dem:
        p = Path(a)
        if p.is_dir():
            paths += sorted(q for q in p.rglob("*") if q.suffix.lower() in DEM_EXT)
        elif p.exists():
            paths.append(p)
    return paths


# ---------------------------------------------------------------- 윤곽

@dataclass
class Footprint:
    fid: str
    props: dict
    xy: np.ndarray  # (n, 2) 닫힌 고리, 국소 m. 합친 윤곽이면 가장 큰 조각
    area: float
    bbox: tuple[float, float, float, float]
    nodes: frozenset = frozenset()  # OSM 노드 id (way 윤곽만)
    parts: tuple = ()               # 합친 윤곽: 조각들의 고리
    segs: np.ndarray | None = None  # 합친 윤곽: 바깥 경계 선분 (m, 2, 2). 조각끼리 맞닿은 선은 뺀다

    def boundary(self) -> np.ndarray:
        if self.segs is not None:
            return self.segs
        return np.stack([self.xy[:-1], self.xy[1:]], axis=1)

    def contains(self, px: float, py: float) -> bool:
        return any(point_in_ring(px, py, r) for r in (self.parts or (self.xy,)))


def ring_area(xy: np.ndarray) -> float:
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def point_in_ring(px: float, py: float, xy: np.ndarray) -> bool:
    x1, y1, x2, y2 = xy[:-1, 0], xy[:-1, 1], xy[1:, 0], xy[1:, 1]
    cross = (y1 > py) != (y2 > py)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
    return bool(np.count_nonzero(cross & (px < xint)) % 2)


def closest_on_segs(px: float, py: float, segs: np.ndarray) -> tuple[float, tuple[float, float]]:
    """선분 모음까지 거리와 그 위의 가장 가까운 점."""
    a, b = segs[:, 0], segs[:, 1]
    ab = b - a
    ap = np.array([px, py]) - a
    l2 = np.einsum("ij,ij->i", ab, ab)
    t = np.clip(np.einsum("ij,ij->i", ap, ab) / np.where(l2 == 0, 1, l2), 0, 1)
    q = a + ab * t[:, None]
    d = np.hypot(q[:, 0] - px, q[:, 1] - py)
    k = int(np.argmin(d))
    return float(d[k]), (float(q[k, 0]), float(q[k, 1]))


def closest_on_ring(px: float, py: float, xy: np.ndarray) -> tuple[float, tuple[float, float]]:
    """경계까지 거리와 경계 위 가장 가까운 점."""
    return closest_on_segs(px, py, np.stack([xy[:-1], xy[1:]], axis=1))


def dist_to_ring(px: float, py: float, xy: np.ndarray) -> float:
    return closest_on_ring(px, py, xy)[0]


def _dist_pts_segs(pts: np.ndarray, segs: np.ndarray) -> np.ndarray:
    """점마다 선분 모음까지의 최단 거리."""
    a, ab = segs[:, 0][None], (segs[:, 1] - segs[:, 0])[None]
    ap = pts[:, None, :] - a
    l2 = np.einsum("ijk,ijk->ij", ab, ab)
    t = np.clip(np.einsum("ijk,ijk->ij", ap, ab) / np.where(l2 == 0, 1, l2), 0, 1)
    d = ap - ab * t[..., None]
    return np.sqrt(np.einsum("ijk,ijk->ij", d, d)).min(axis=1)


def _split_segs(xy: np.ndarray, max_len: float) -> np.ndarray:
    """고리를 max_len 이하 선분들로."""
    out = []
    for a, b in zip(xy[:-1], xy[1:]):
        n = max(1, math.ceil(math.hypot(*(b - a)) / max_len))
        t = np.linspace(0, 1, n + 1)[:, None]
        pts = a + (b - a) * t
        out.append(np.stack([pts[:-1], pts[1:]], axis=1))
    return np.concatenate(out)


def _sheet(fp: Footprint) -> str | None:
    """수치지형도 윤곽의 도엽 (fid = topo/<도엽>/<번호>)."""
    parts = fp.fid.split("/")
    return parts[1] if len(parts) == 3 and parts[0] == "topo" else None


def merge_split_pieces(fps: list[Footprint], tol: float = 0.2, min_shared: float = 1.0) -> tuple[list[Footprint], int]:
    """도엽 경계에서 잘린 수치지형도 건물 조각을 합친다. 다른 도엽의 두 윤곽이 맞닿은 선은 도엽 경계일 수밖에 없으므로,
    tol m 안에서 min_shared m 이상 맞닿으면 한 건물로 본다. 합친 윤곽의 둘레에서 맞닿은 선은 뺀다.
    반환: (새 윤곽 목록, 합친 묶음 수)"""
    idx = [i for i, fp in enumerate(fps) if _sheet(fp)]
    parent = {i: i for i in idx}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    fine: dict[int, np.ndarray] = {}

    def split(i):
        if i not in fine:
            fine[i] = _split_segs(fps[i].xy, 1.0)
        return fine[i]

    if idx:
        sheets = np.asarray([_sheet(fps[i]) for i in idx])
        box = np.asarray([fps[i].bbox for i in idx], float)
        for n, i in enumerate(idx[:-1]):
            rest = slice(n + 1, None)
            cand = ((sheets[rest] != sheets[n]) & (box[rest, 0] <= box[n, 2] + tol) & (box[n, 0] <= box[rest, 2] + tol)
                    & (box[rest, 1] <= box[n, 3] + tol) & (box[n, 1] <= box[rest, 3] + tol))
            for m in np.flatnonzero(cand):
                j = idx[n + 1 + int(m)]
                segs = split(i)
                near = _dist_pts_segs(segs.mean(axis=1), fps[j].boundary()) <= tol
                if np.hypot(*(segs[near, 1] - segs[near, 0]).T).sum() >= min_shared:
                    parent[root(i)] = root(j)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in idx:
        groups[root(i)].append(i)
    merged_of = {g[0]: g for g in groups.values() if len(g) > 1}
    in_group = {i for g in merged_of.values() for i in g}
    out = []
    for i, fp in enumerate(fps):
        if i not in in_group:
            out.append(fp)
            continue
        if i not in merged_of:
            continue
        pieces = [fps[k] for k in merged_of[i]]
        keep = []
        for k, p in zip(merged_of[i], pieces):
            others = np.concatenate([q.boundary() for q in pieces if q is not p])
            segs = split(k)
            keep.append(segs[_dist_pts_segs(segs.mean(axis=1), others) > tol])
        big = max(pieces, key=lambda p: p.area)
        props = dict(big.props)
        props["name"] = next((p.props.get("name") for p in pieces if p.props.get("name")), "")
        props["ref"] = ";".join(sorted(set().union(*(refs_of(p) for p in pieces))))
        boxes = np.asarray([p.bbox for p in pieces])
        out.append(Footprint("+".join(sorted(p.fid for p in pieces)), props, big.xy, sum(p.area for p in pieces),
                             (boxes[:, 0].min(), boxes[:, 1].min(), boxes[:, 2].max(), boxes[:, 3].max()),
                             frozenset(), tuple(p.xy for p in pieces), np.concatenate(keep)))
    return out, len(merged_of)


def _near_bbox(fp: Footprint, px: float, py: float, d: float) -> bool:
    x0, y0, x1, y1 = fp.bbox
    return x0 - d <= px <= x1 + d and y0 - d <= py <= y1 + d


def load_footprints(path: Path, proj: LocalProj) -> list[Footprint]:
    data = json.loads(path.read_text(encoding="utf-8"))
    fps = []
    for f in data.get("features", []):
        g = f.get("geometry") or {}
        if g.get("type") != "Polygon" or not g.get("coordinates"):
            continue
        ring = np.asarray(g["coordinates"][0], float)
        if len(ring) < 3:
            continue
        if not np.allclose(ring[0], ring[-1]):
            ring = np.vstack([ring, ring[:1]])
        if len(ring) < 4:
            continue
        x, y = proj.fwd(ring[:, 0], ring[:, 1])
        xy = np.column_stack([x, y])
        p = dict(f.get("properties") or {})
        nodes = frozenset(int(n) for n in p.pop("nodes", None) or [])
        fid = p.get("fid") or (f"osm-{p.get('osm_type', 'way')}/{p.get('osm_id', '?')}"
                               + (f"#{p['part']}" if p.get("part") else ""))
        fps.append(Footprint(fid, p, xy, abs(ring_area(xy)), (x.min(), y.min(), x.max(), y.max()), nodes))
    return fps


def refs_of(fp: Footprint) -> set[str]:
    """윤곽에 적힌 동 번호. OSM ref, 수치지형도는 주기에서 뽑은 번호(여럿이면 ';')."""
    return {s.strip() for s in str(fp.props.get("ref", "") or "").split(";") if s.strip()}


def number_conflict(bid: str, refs: set[str]) -> bool:
    """윤곽에 적힌 동 번호가 이 건물과 다른가. 59-1동 건물에 '59동'이 적힌 것처럼 본 번호가 같으면 같은 건물로 본다."""
    if not refs:
        return False
    base = bid.split("-")[0]
    return not any(r == bid or r.split("-")[0] == base for r in refs)


def match_footprint(bid: str, px: float, py: float, fps: list[Footprint], max_dist: float = 20.0,
                    ref_dist: float = 80.0, ref_first: bool = True) -> tuple[Footprint | None, str]:
    """캠퍼스맵 좌표에 맞는 윤곽. ① ref(동 번호)가 같은 윤곽(80 m 이내) ② 좌표를 품은 윤곽(가장 작은 것)
    ③ 경계까지 max_dist 이내에서 가장 가까운 윤곽(본 번호가 다른 동 번호가 적힌 윤곽은 뺀다). 없으면 None.
    ref_first=False 면 ②를 ①보다 먼저 본다(수치지형도 주기는 가끔 틀려서 좌표를 더 믿는다)."""
    def by_ref():
        refs = [fp for fp in fps if bid in refs_of(fp) and _near_bbox(fp, px, py, ref_dist)]
        if not refs:
            return None
        dists = [0.0 if fp.contains(px, py) else closest_on_segs(px, py, fp.boundary())[0] for fp in refs]
        k = int(np.argmin(dists))
        return refs[k] if dists[k] <= ref_dist else None

    def by_inside():
        inside = [fp for fp in fps if _near_bbox(fp, px, py, 0) and fp.contains(px, py)]
        return min(inside, key=lambda fp: fp.area) if inside else None

    for how, find in ((("ref", by_ref), ("inside", by_inside)) if ref_first else
                      (("inside", by_inside), ("ref", by_ref))):
        fp = find()
        if fp is not None:
            return fp, how
    best, best_d = None, max_dist
    for fp in fps:
        if not _near_bbox(fp, px, py, max_dist) or number_conflict(bid, refs_of(fp)):
            continue
        d = closest_on_segs(px, py, fp.boundary())[0]
        if d <= best_d:
            best, best_d = fp, d
    return (best, "near") if best is not None else (None, "none")


def pick_footprints(bid: str, px: float, py: float, topo: list[Footprint], osm: list[Footprint],
                    max_dist: float = 20.0) -> tuple[Footprint | None, str, Footprint | None]:
    """(둘레에 쓸 윤곽, 고른 방법, 출입구 후보를 더 가져올 같은 건물의 OSM 윤곽).
    수치지형도 윤곽(좌표를 품음 → 주기의 동 번호) → OSM(ref → 좌표를 품음) → 20 m 이내(수치지형도 → OSM).
    좌표를 품은 수치지형도 윤곽에 다른 동 번호가 적혀 있고 OSM ref가 맞으면 OSM을 쓴다."""
    t_fp, t_how = match_footprint(bid, px, py, topo, max_dist, ref_first=False) if topo else (None, "none")
    o_fp, o_how = match_footprint(bid, px, py, osm, max_dist) if osm else (None, "none")
    if t_how in ("inside", "ref") and not (o_how == "ref" and number_conflict(bid, refs_of(t_fp))):
        fp, how = t_fp, t_how
    elif o_how in ("ref", "inside"):
        fp, how = o_fp, o_how
    elif t_fp is not None:
        fp, how = t_fp, t_how
    else:
        fp, how = o_fp, o_how
    same_osm = None
    if o_fp is not None and fp is not None:
        if o_fp is fp or o_how in ("ref", "inside"):
            same_osm = o_fp
        else:
            cx, cy = o_fp.xy[:-1].mean(axis=0)
            same_osm = o_fp if fp.contains(float(cx), float(cy)) else None
    return fp, how, same_osm


def nearest_footprint(px: float, py: float, fps: list[Footprint], max_d: float):
    """경계가 max_d 이내인 가장 가까운 윤곽과 그 경계 위 점."""
    best, best_d, best_q = None, max_d, None
    for fp in fps:
        if not _near_bbox(fp, px, py, max_d):
            continue
        d, q = closest_on_segs(px, py, fp.boundary())
        if d <= best_d:
            best, best_d, best_q = fp, d, q
    return best, best_q


def segment_samples(segs: np.ndarray, step: float) -> tuple[np.ndarray, np.ndarray]:
    """선분들을 step 이하 조각으로 나눠 각 조각 가운데 점과 그 조각 길이(가중치)."""
    pts, wts = [], []
    for (x1, y1), (x2, y2) in segs:
        length = math.hypot(x2 - x1, y2 - y1)
        if length == 0:
            continue
        n = max(1, math.ceil(length / step))
        for k in range(n):
            s = (k + 0.5) / n
            pts.append((x1 + (x2 - x1) * s, y1 + (y2 - y1) * s))
            wts.append(length / n)
    return np.asarray(pts, float), np.asarray(wts, float)


def perimeter_samples(xy: np.ndarray, step: float) -> tuple[np.ndarray, np.ndarray]:
    """둘레를 step 이하 조각으로 나눠 각 조각 가운데 점과 그 조각 길이(가중치)."""
    return segment_samples(np.stack([xy[:-1], xy[1:]], axis=1), step)


def circle_samples(px: float, py: float, radius: float, n: int = 36) -> tuple[np.ndarray, np.ndarray]:
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pts = np.column_stack([px + radius * np.cos(ang), py + radius * np.sin(ang)])
    return pts, np.full(n, 2 * np.pi * radius / n)


# ---------------------------------------------------------------- 출입구

@dataclass
class Cand:
    x: float
    y: float
    source: str
    kind: str = ""
    osm_id: str = ""
    osm_level: str = ""
    floor_checked: str = ""
    note: str = ""


def parse_floor(s) -> int | None:
    """'3', '3층', '3F', 'B1', '지하1층', '-1' → 층 번호 n (1층 = 0, 2층 = 1, 지하1층 = -1)."""
    s = str(s or "").strip().replace(" ", "").replace("층", "").upper()
    if not s:
        return None
    m = re.fullmatch(r"(?:B|지하)(\d+)F?", s)
    if m:
        return -int(m.group(1)) if int(m.group(1)) > 0 else None
    m = re.fullmatch(r"(-?\d+)F?", s)
    if m:
        v = int(m.group(1))
        return v - 1 if v > 0 else (v if v < 0 else None)
    return None


def floor_label(n: int) -> str:
    return f"{n + 1}층" if n >= 0 else f"지하{-n}층"


def usable_path(p: dict) -> bool:
    """지상 보행로만. 다리·터널·실내 통로는 지상 출입이 아니다."""
    if p.get("highway") not in WALK:
        return False
    return all(str(p.get(k, "") or "") in ("", "no") for k in ("bridge", "tunnel", "indoor"))


def load_points(path: Path, proj: LocalProj) -> list[tuple[float, float, dict]]:
    if not path.exists():
        return []
    out = []
    for f in json.loads(path.read_text(encoding="utf-8")).get("features", []):
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        x, y = proj.fwd(g["coordinates"][0], g["coordinates"][1])
        out.append((float(x), float(y), f.get("properties") or {}))
    return out


def load_paths(path: Path, proj: LocalProj) -> list[tuple[np.ndarray, list[int], dict]]:
    if not path.exists():
        return []
    out = []
    for f in json.loads(path.read_text(encoding="utf-8")).get("features", []):
        g = f.get("geometry") or {}
        p = f.get("properties") or {}
        if g.get("type") != "LineString" or len(g.get("coordinates") or []) < 2 or not usable_path(p):
            continue
        arr = np.asarray(g["coordinates"], float)
        x, y = proj.fwd(arr[:, 0], arr[:, 1])
        nodes = [int(n) for n in p.get("nodes") or []]
        out.append((np.column_stack([x, y]), nodes if len(nodes) == len(arr) else [], p))
    return out


def dedupe(cands: list[Cand], merge_dist: float) -> list[Cand]:
    """merge_dist 안의 후보는 하나로. 수동 > entrance 태그 > 보행로 공유 노드 > 보행로 끝점, 같으면 main 우선."""
    kept: list[Cand] = []
    for c in sorted(cands, key=lambda c: (SOURCE_RANK.get(c.source, 9), c.kind != "main", c.x, c.y)):
        if all(math.hypot(c.x - k.x, c.y - k.y) > merge_dist for k in kept):
            kept.append(c)
    return kept


def entrance_candidates(fps: list[Footprint], entrances, paths, *, entrance_dist: float = 3.0,
                        end_dist: float = 2.5, merge_dist: float = 6.0) -> dict[str, list[Cand]]:
    """윤곽(fid)별 지상 출입구 후보."""
    by_node: dict[int, list[Footprint]] = defaultdict(list)
    for fp in fps:
        for n in fp.nodes:
            by_node[n].append(fp)
    cands: dict[str, list[Cand]] = defaultdict(list)
    for x, y, p in entrances:
        nid = int(p.get("osm_id") or 0)
        owners = by_node.get(nid)
        if owners:
            targets = [(fp, (x, y)) for fp in owners]
        else:
            fp, q = nearest_footprint(x, y, fps, entrance_dist)
            targets = [(fp, q)] if fp is not None else []
        for fp, q in targets:
            cands[fp.fid].append(Cand(q[0], q[1], "osm-entrance", str(p.get("entrance") or "yes"),
                                      str(nid), str(p.get("level") or "")))
    for xy, nodes, p in paths:
        pid = str(p.get("osm_id", ""))
        for k, nid in enumerate(nodes):
            for fp in by_node.get(nid, []):
                cands[fp.fid].append(Cand(float(xy[k, 0]), float(xy[k, 1]), "osm-path-join", "", pid))
        for k in sorted({0, len(xy) - 1}):
            if nodes and nodes[k] in by_node:
                continue
            fp, q = nearest_footprint(float(xy[k, 0]), float(xy[k, 1]), fps, end_dist)
            if fp is not None:
                cands[fp.fid].append(Cand(q[0], q[1], "osm-path-end", "", pid))
    return {fid: dedupe(cs, merge_dist) for fid, cs in cands.items()}


def load_manual(path: Path, proj: LocalProj) -> dict[str, list[Cand]]:
    out: dict[str, list[Cand]] = defaultdict(list)
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            b = (r.get("building") or "").strip()
            try:
                lat, lon = float(r["lat"]), float(r["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            x, y = proj.fwd(lon, lat)
            n = parse_floor(r.get("floor"))
            out[b].append(Cand(float(x), float(y), "manual", (r.get("kind") or "").strip(), "", "",
                               floor_label(n) if n is not None else "", (r.get("note") or "").strip()))
    return out


# ---------------------------------------------------------------- 건물

def building_key(b: str):
    """동 번호 순: 9 < 43 < 43-2 < 43-10 < 301, 919 < 919A < 919B < 920. 번호가 아닌 것(GATE)은 맨 뒤."""
    m = re.fullmatch(r"(\d+)[A-Z]?(?:-(\d+))?", b)
    return (0, int(m.group(1)), int(m.group(2) or 0), b) if m else (1, 0, 0, b)


def load_buildings(paths: list[Path]) -> dict[str, dict]:
    """앞 파일 우선. 앞 파일에 좌표가 없으면 뒤 파일(수동 좌표 등)로 채운다. 끝까지 없으면 note 에 적는다."""
    rows: dict[str, dict] = {}
    for path in paths:
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                b = (r.get("building") or "").strip()
                if not b:
                    continue
                try:
                    lat, lon = float(r["lat"]), float(r["lon"])
                except (KeyError, TypeError, ValueError):
                    lat = lon = None
                if b in rows:
                    if rows[b]["lat"] is None and lat is not None:
                        rows[b].update(lat=lat, lon=lon, source=f"{rows[b]['source']}+{path.name}")
                    continue
                rows[b] = {"building": b, "name": (r.get("name") or "").strip(), "lat": lat, "lon": lon,
                           "source": path.name}
    return rows


def lecture_set(path: Path) -> set[str] | None:
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {(r.get("building") or "").strip() for r in csv.DictReader(f)}


def _entrance_rows(b: str, name: str, cands: list[Cand], dem: Dem, proj: LocalProj,
                   first_floor: float | None, floor_h: float) -> list[dict]:
    if not cands:
        return []
    lons, lats = proj.inv([c.x for c in cands], [c.y for c in cands])
    lons, lats = np.atleast_1d(lons), np.atleast_1d(lats)
    ground = dem.sample(lons, lats)
    rows = []
    for c, lon, lat, g in zip(cands, lons, lats, ground):
        r = {k: "" for k in ENT_FIELDS}
        r.update(building=b, name=name, lat=f"{lat:.6f}", lon=f"{lon:.6f}", kind=c.kind, source=c.source,
                 osm_id=c.osm_id, osm_level=c.osm_level, floor_checked=c.floor_checked, note=c.note)
        if not np.isnan(g):
            r["ground_m"] = f"{g:.1f}"
            if first_floor is not None:
                rel = float(g) - first_floor
                r["rel_to_1f_m"] = f"{rel:+.1f}"
                r["floor_est"] = floor_label(math.floor(rel / floor_h + 0.5))
        rows.append(r)
    rows.sort(key=lambda r: (float(r["ground_m"]) if r["ground_m"] else 1e9, r["lon"]))
    for i, r in enumerate(rows, 1):
        r["entrance_no"] = str(i)
    return rows


def _floor_order(label: str) -> int:
    n = parse_floor(label)
    return n if n is not None else 999


def estimate(buildings: dict[str, dict], fps: list[Footprint], dem: Dem, proj: LocalProj, *,
             entrances=(), paths=(), manual: dict[str, list[Cand]] | None = None,
             step: float = 2.0, radius: float = 15.0, match_dist: float = 20.0, slope: float = 3.0,
             floor_h: float = 4.0, lobby_tol: float = 1.5, lectures: set[str] | None = None,
             entrance_dist: float = 3.0, end_dist: float = 2.5, merge_dist: float = 6.0
             ) -> tuple[list[dict], list[dict]]:
    manual = manual or {}
    ent_by_fid = entrance_candidates(fps, entrances, paths, entrance_dist=entrance_dist, end_dist=end_dist,
                                     merge_dist=merge_dist) if fps else {}
    topo = [fp for fp in fps if fp.fid.startswith("topo/")]
    osm = [fp for fp in fps if not fp.fid.startswith("topo/")]
    out, ent_out = [], []
    for b in sorted(buildings, key=building_key):
        info = buildings[b]
        row = {k: "" for k in FIELDS}
        row.update(building=b, name=info["name"])
        if lectures is not None:
            row["lecture_building"] = "Y" if b in lectures else "N"
        if info["lat"] is None:
            row["note"] = "좌표 없음"
            out.append(row)
            continue
        row.update(lat=f"{info['lat']:.6f}", lon=f"{info['lon']:.6f}")
        px, py = (float(v) for v in proj.fwd(info["lon"], info["lat"]))
        fp, how, same_osm = pick_footprints(b, px, py, topo, osm, max_dist=match_dist)
        if fp is not None:
            segs = fp.boundary()
            pts, wts = segment_samples(segs, step)
            row.update(footprint=fp.fid, footprint_name=str(fp.props.get("name", "") or ""), footprint_match=how,
                       perimeter_m=f"{float(np.hypot(*(segs[:, 1] - segs[:, 0]).T).sum()):.0f}")
        else:
            pts, wts = circle_samples(px, py, radius)
            row.update(footprint=f"ring{radius:g}m", footprint_match="none")
        lons, lats = proj.inv(pts[:, 0], pts[:, 1])
        vals = dem.sample(lons, lats)
        ok = ~np.isnan(vals)
        point_val = float(dem.sample([info["lon"]], [info["lat"]])[0])
        if not np.isnan(point_val):
            row["point_ground_m"] = f"{point_val:.1f}"
            row["dem"] = dem.source_at(info["lon"], info["lat"])
        if ok.sum() == 0:
            row["note"] = "DEM 범위 밖"
            out.append(row)
            continue

        notes = []
        v, w = vals[ok], wts[ok]
        mean = float(np.sum(v * w) / np.sum(w))
        lo, hi = float(v.min()), float(v.max())
        sloped = hi - lo >= slope
        row.update(first_floor_est_m=f"{mean:.1f}", ground_min_m=f"{lo:.1f}", ground_max_m=f"{hi:.1f}",
                   ground_span_m=f"{hi - lo:.1f}", slope_site="Y" if sloped else "N", samples=str(int(ok.sum())))
        if ok.mean() < 0.8:
            notes.append(f"둘레의 {ok.mean():.0%}만 DEM 범위 안")
        if fp is None:
            notes.append("윤곽 없음(원형 표본)")
        elif number_conflict(b, refs_of(fp)):
            notes.append(f"윤곽에 적힌 동 번호가 다름({'/'.join(sorted(refs_of(fp)))}) → 윤곽 확인 필요")

        # 출입구: 수동 입력이 있으면 그것만, 없으면 윤곽(과 같은 건물의 OSM 윤곽)의 자동 후보
        cands = manual.get(b)
        if not cands and fp is not None:
            cands = list(ent_by_fid.get(fp.fid, []))
            if same_osm is not None and same_osm is not fp:
                cands = dedupe(cands + ent_by_fid.get(same_osm.fid, []), merge_dist)
        ents = _entrance_rows(b, info["name"], cands, dem, proj, mean, floor_h)
        ent_out += ents
        heights = [float(e["ground_m"]) for e in ents if e["ground_m"]]
        floors = sorted({e["floor_checked"] or e["floor_est"] for e in ents if e["floor_checked"] or e["floor_est"]},
                        key=_floor_order)
        row["entrances"] = str(len(ents)) if ents else "0"
        if heights:
            row.update(entrance_min_m=f"{min(heights):.1f}", entrance_max_m=f"{max(heights):.1f}")
        if floors:
            row["entrance_floors"] = "/".join(floors)
            row["multi_level_access"] = "Y" if len(floors) >= 2 else "N"

        # 로비층
        mains = [float(e["ground_m"]) for e in ents if e["kind"] == "main" and e["ground_m"]]
        if mains and max(mains) - min(mains) < lobby_tol:
            row.update(lobby_est_m=f"{sum(mains) / len(mains):.1f}", lobby_source="main 출입구")
        elif not mains and heights and max(heights) - min(heights) < lobby_tol:
            row.update(lobby_est_m=f"{sum(heights) / len(heights):.1f}", lobby_source="출입구 평균")
        elif not heights and not sloped:
            row.update(lobby_est_m=f"{mean:.1f}", lobby_source="1층 기준면(평지)")
        if len(floors) >= 2:
            notes.append(f"지상 출입구 {len(ents)}곳이 {row['entrance_floors']}")
        if not row["lobby_est_m"]:
            notes.append("로비층 확정 필요" + ("(출입구가 여러 높이)" if heights else "(경사지, 출입구 정보 없음)"))
        row["note"] = "; ".join(notes)
        out.append(row)
    return out, ent_out


def _write(rows: list[dict], fields: list[str], csv_path: Path) -> Path:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    gj = csv_path.with_suffix(".geojson")
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
              "properties": r} for r in rows if r["lat"]]
    gj.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    return gj


def write_outputs(rows: list[dict], csv_path: Path) -> Path:
    return _write(rows, FIELDS, csv_path)


def write_entrances(rows: list[dict], csv_path: Path) -> Path:
    return _write(rows, ENT_FIELDS, csv_path)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # cmd에서 로그를 파일로 저장할 때 cp949에 없는 글자가 있어도 멈추지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", nargs="+", default=[str(DEM_DIR)], help="DEM 파일이나 폴더 (기본 data/dem)")
    ap.add_argument("--dem-crs", default=None, help="DEM 좌표계를 직접 지정 (예: EPSG:5186)")
    ap.add_argument("--buildings", nargs="+", default=[str(CAMPUS), str(BUILDINGS)])
    ap.add_argument("--footprints", nargs="+", default=["auto"],
                    help="윤곽 GeoJSON. auto = 수치지형도(topo_buildings)와 OSM 둘 다(있는 것만). none = 모두 원형 표본")
    ap.add_argument("--entrances", default=str(ENTRANCES))
    ap.add_argument("--paths", default=str(PATHS))
    ap.add_argument("--manual", default=str(MANUAL))
    ap.add_argument("--step", type=float, default=2.0)
    ap.add_argument("--radius", type=float, default=15.0)
    ap.add_argument("--match-dist", type=float, default=20.0)
    ap.add_argument("--slope", type=float, default=3.0)
    ap.add_argument("--floor-height", type=float, default=4.0)
    ap.add_argument("--margin", type=float, default=0.005, help="DEM을 읽을 범위: 건물 좌표 범위 ± 이 값(도)")
    ap.add_argument("--entrance-dist", type=float, default=3.0, help="출입구 노드를 윤곽에 붙일 거리(m)")
    ap.add_argument("--end-dist", type=float, default=2.5, help="보행로 끝점을 출입구로 볼 벽과의 거리(m)")
    ap.add_argument("-o", "--output", default=str(OUT_CSV))
    ap.add_argument("--entrance-output", default=str(OUT_ENT))
    args = ap.parse_args()

    paths = dem_paths(args.dem)
    if not paths:
        raise SystemExit(f"DEM 파일이 없음: {args.dem}\n국토정보플랫폼에서 공개DEM(.img)을 받아 data/dem 에 넣고 다시 실행")

    proj = LocalProj()
    buildings = load_buildings([Path(p) for p in args.buildings])
    lats = [b["lat"] for b in buildings.values() if b["lat"] is not None]
    lons = [b["lon"] for b in buildings.values() if b["lon"] is not None]
    m = args.margin
    bbox = (min(lats) - m, min(lons) - m, max(lats) + m, max(lons) + m) if lats else None

    dem = Dem(paths, args.dem_crs, bbox=bbox)
    print(f"DEM {len(dem.layers)}장 사용(촘촘한 것부터)" + (f" · 캠퍼스와 겹치지 않아 건너뜀: {dem.skipped}" if dem.skipped else ""))
    if not dem.layers:
        raise SystemExit("캠퍼스 범위를 덮는 DEM이 없음. 관악캠퍼스는 1:50,000 '안양' 도엽(북위 37°30' 남쪽)에 있다")
    for L in dem.layers:
        w, s, e, n = L.bounds_wgs84()
        epsg = L.crs.to_epsg()
        wkt = L.crs.to_wkt()
        print(f"  {L.name}: {'EPSG:' + str(epsg) if epsg else wkt[:60]} · 격자 {L.res[0]:g}×{L.res[1]:g} m · "
              f"전체 {L.full_size[0]}×{L.full_size[1]}칸 중 {L.arr.shape[1]}×{L.arr.shape[0]}칸 읽음 · "
              f"범위 위도 {s:.4f}~{n:.4f}, 경도 {w:.4f}~{e:.4f} · 값 {np.nanmin(L.arr):.1f}~{np.nanmax(L.arr):.1f} m")
        if any(k in wkt for k in ("Bessel", "Tokyo", "Korean_1985", "Korean 1985")):
            print("    ※ 베셀 타원체(옛 측지계) 좌표계라 위치가 수백 m 어긋날 수 있음. 정문·301동 고도가 상식과 맞는지 확인")

    fp_paths: list[Path] = []
    for a in args.footprints:
        if a == "auto":
            fp_paths += [p for p in (TOPO_FOOTPRINTS, FOOTPRINTS) if p.exists()]
        elif a != "none" and Path(a).exists():
            fp_paths.append(Path(a))
    fps: list[Footprint] = []
    for p in fp_paths:
        fps += load_footprints(p, proj)
    n_topo = sum(1 for fp in fps if fp.fid.startswith("topo/"))
    fps, n_merged = merge_split_pieces(fps)
    print(f"윤곽: {', '.join(p.name for p in fp_paths) if fp_paths else '없음(모두 원형 표본)'}"
          + (f" · 수치지형도 {n_topo}개(도엽 경계에서 잘린 조각을 합쳐 {n_merged}묶음)" if n_topo else ""))
    entrances = load_points(Path(args.entrances), proj)
    walk = load_paths(Path(args.paths), proj)
    manual = load_manual(Path(args.manual), proj)
    print(f"건물 {len(buildings)}개 · 윤곽 {len(fps)}개 · OSM 출입구 노드 {len(entrances)}개 · 지상 보행로 {len(walk)}개"
          f" · 수동 출입구 {sum(len(v) for v in manual.values())}개({len(manual)}개 동)")

    rows, ents = estimate(buildings, fps, dem, proj, entrances=entrances, paths=walk, manual=manual,
                          step=args.step, radius=args.radius, match_dist=args.match_dist, slope=args.slope,
                          floor_h=args.floor_height, lectures=lecture_set(HISTORY),
                          entrance_dist=args.entrance_dist, end_dist=args.end_dist)
    gj = write_outputs(rows, Path(args.output))
    egj = write_entrances(ents, Path(args.entrance_output))

    done = [r for r in rows if r["first_floor_est_m"]]
    by_match = {k: sum(1 for r in done if r["footprint_match"] == k) for k in ("ref", "inside", "near", "none")}
    by_src = defaultdict(int)
    for e in ents:
        by_src[e["source"]] += 1
    print(f"\n저장: {args.output}, {gj}")
    print(f"      {args.entrance_output}, {egj}")
    print(f"  고도 추정 {len(done)}/{len(rows)}개 · 윤곽 사용 ref {by_match['ref']}, 안 {by_match['inside']}, "
          f"근처 {by_match['near']} · 원형 표본 {by_match['none']}")
    print(f"  경사지(둘레 고도차 ≥ {args.slope:g} m): {sum(1 for r in done if r['slope_site'] == 'Y')}개")
    print(f"  출입구 {len(ents)}곳 ({dict(by_src)}) · 출입구 있는 건물 {sum(1 for r in done if r['entrances'] not in ('', '0'))}개"
          f" · 여러 층으로 출입 {sum(1 for r in done if r['multi_level_access'] == 'Y')}개")
    print(f"  로비층 확정 {sum(1 for r in done if r['lobby_est_m'])}개 · 확정 필요 {sum(1 for r in done if not r['lobby_est_m'])}개")
    if done:
        srt = sorted(done, key=lambda r: float(r["first_floor_est_m"]))
        fmt = lambda r: f"{r['building']} {r['name']} {r['first_floor_est_m']} m"  # noqa: E731
        print(f"  가장 낮은 곳: {', '.join(fmt(r) for r in srt[:3])}")
        print(f"  가장 높은 곳: {', '.join(fmt(r) for r in srt[-3:])}")
    missing = [r["building"] for r in rows if not r["first_floor_est_m"]]
    if missing:
        print(f"  고도 없음 {len(missing)}개 (좌표 없음 또는 DEM 범위 밖. 도엽을 더 받거나 --dem-crs 확인): {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
