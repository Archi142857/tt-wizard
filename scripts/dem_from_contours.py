"""수치지형도(국토정보플랫폼, SHP)의 등고선·표고점으로 캠퍼스 DEM을 만들고, 건물 윤곽을 GeoJSON으로 뽑는다.

  python scripts/dem_from_contours.py                    # data/topo 아래 SHP 전부 → data/dem/topo_dem.tif, data/topo_buildings.geojson
  python scripts/dem_from_contours.py --scale 1000       # 1:1,000으로 만들기 (기본은 1:5,000)
  python scripts/dem_from_contours.py --extent campus    # 건물 좌표 범위만 (기본은 받은 도엽 전체 — 도로 그래프까지 덮는다)
  python scripts/dem_from_contours.py --crs EPSG:5186    # .prj 파일이 없을 때만 좌표계 지정 (기본 EPSG:5186)

국토정보플랫폼의 공개 DEM은 90 m 격자라 건물 단위 고도를 구하기엔 거칠다. 수치지형도의 등고선(5 m 간격)과
표고점을 삼각망(TIN)으로 선형 보간하면 2 m 격자 DEM이 된다.

입력  data/topo/<압축 파일마다 폴더>/ 아래의 SHP. 도엽마다 파일 이름이 같으므로 한 폴더에 섞어 풀면 덮어쓴다.
      원본은 저장소에 없다(국외 반출 금지 자료). 국토정보플랫폼에서 받아 PC 에 둔다: docs/topo.md
      레이어는 파일 이름에 든 코드로 구분한다.
        F0010000 등고선 — 높이 필드 '등고수치'
        F0020000 표고점 — 높이 필드 '수치'
        B0010000 건물   — 윤곽. '주기'(예: 인문대학1동)를 이름으로, 거기 든 동 번호를 ref 로 쓴다
      축척은 경로에 든 도엽번호 자릿수로 구분한다: 8자리(37612018) = 1:5,000, 9자리(376120571) = 1:1,000.
      관악캠퍼스는 1:5,000 도엽 37612018, 37612019, 37612028, 37612029 네 장에 들어간다.
출력  data/dem/topo_dem.tif        --scale 축척(기본 1:5,000)의 등고선·표고점으로 만든 2 m 격자. 받은 도엽 전체 범위
      data/topo_buildings.geojson  같은 축척의 건물 윤곽. 도엽 경계에서 잘린 조각은 building_elevation.py 가 합친다
      다른 축척의 표고점은 DEM에 넣지 않고 검증점으로 써서 오차를 로그에 찍는다.

1:5,000을 기본으로 쓰는 이유: 국토정보플랫폼의 관악캠퍼스 1:1,000 도엽에는 1 m 주곡선 없이 5 m 계곡선만 있고
(1:5,000 등고선과 평균 0.1 m 차이), 표고점이 도엽당 3개뿐이다. 1:5,000은 도엽 4장에 표고점이 2,276개 있다.

한계  등고선 사이는 직선으로 채워지고, 표고점이 없는 봉우리·골짜기 바닥은 평평하게 나올 수 있다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TOPO = DATA / "topo"
OUT = DATA / "dem" / "topo_dem.tif"
OUT_BLD = DATA / "topo_buildings.geojson"
BUILDING_LISTS = [DATA / "campus_buildings.csv", DATA / "buildings.csv"]
CONTOUR, SPOT, BUILDING = "F0010000", "F0020000", "B0010000"
LAYER_NAME = {CONTOUR: "등고선", SPOT: "표고점", BUILDING: "건물"}
HEIGHT_FIELDS = ("등고수치", "수치", "표고수치", "표고", "높이", "HEIGHT", "ELEV", "CONT", "Z")
HEIGHT_HINTS = ("수치", "표고", "높이", "HEIGHT", "ELEV", "CONT", "HGT", "ALT")
LABEL_FIELDS = ("주기", "명칭", "건물명", "NAME", "이름")  # 주기: '인문대학1동', 명칭: 캠퍼스는 모두 '서울대학교'
LEVEL_FIELDS = ("층수", "지상층수", "LEVELS")
KIND_FIELDS = ("종류",)  # 주택외건물, 무벽건물(지붕만), 가건물 …
SHEET_RE = re.compile(r"(?<!\d)(3[3-8]\d{6,8})(?!\d)")  # 도엽번호: 북위 33~38도로 시작하는 8~10자리
DONG_RE = re.compile(r"(?<![\d-])(\d{1,3}(?:-\d{1,2})?)동")  # '사범대학10-1동교육정보관' → 10-1
SCALES = ("5000", "1000")
SMALL_SHEET_M = 1200.0  # 1:1,000 도엽은 한 변이 약 0.5 km, 1:5,000 도엽은 2 km 넘는다


def sheet_of(path: Path) -> str | None:
    found = SHEET_RE.findall(str(path))
    return found[-1] if found else None


def scale_of(path: Path) -> str | None:
    s = sheet_of(path)
    if s is None:
        return None
    return "1000" if len(s) >= 9 else "5000"


def layer_of(path: Path) -> str | None:
    stem = path.stem.upper()
    return next((c for c in (CONTOUR, SPOT, BUILDING) if c in stem), None)


def dong_refs(label: str) -> list[str]:
    """건물 주기에 든 동 번호들."""
    return list(dict.fromkeys(DONG_RE.findall(label or "")))


def _group(path: Path, root: Path) -> str:
    """압축 파일 하나(= 도엽 하나)를 푼 폴더. root 바로 아래 폴더 이름."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return str(path.parent)
    return parts[0] if len(parts) > 1 else path.stem


def open_shp(path: Path):
    """국토정보플랫폼 SHP는 CP949(EUC-KR). 안 되면 UTF-8, 그래도 안 되면 깨진 글자만 바꿔 읽는다."""
    import warnings

    import shapefile

    with warnings.catch_warnings():  # .cpg 의 'EUC-KR'과 cp949가 다르다는 경고는 무시 (cp949가 EUC-KR을 포함)
        warnings.simplefilter("ignore")
        for enc in ("cp949", "utf-8"):
            try:
                r = shapefile.Reader(str(path), encoding=enc)
                if len(r):
                    r.record(0)
                return r
            except UnicodeDecodeError:
                continue
        return shapefile.Reader(str(path), encoding="cp949", encodingErrors="replace")


def crs_of(path: Path, default: str):
    from rasterio.crs import CRS

    prj = path.with_suffix(".prj")
    if prj.exists():
        try:
            return CRS.from_user_input(prj.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return CRS.from_user_input(default)


def _to(xs, ys, src, dst):
    if src == dst:
        return np.asarray(xs, float), np.asarray(ys, float)
    from rasterio.warp import transform
    x, y = transform(src, dst, list(xs), list(ys))
    return np.asarray(x, float), np.asarray(y, float)


def _extent_m(paths: list[Path], default_crs: str) -> float:
    """자료가 퍼진 범위의 긴 변(m)."""
    boxes = []
    for p in paths:
        r = open_shp(p)
        if len(r):
            x0, y0, x1, y1 = r.bbox[:4]
            xs, ys = _to([x0, x1, x0, x1], [y0, y0, y1, y1], crs_of(p, default_crs), "EPSG:5186")
            boxes.append((xs.min(), ys.min(), xs.max(), ys.max()))
        r.close()
    if not boxes:
        return 0.0
    a = np.asarray(boxes)
    return float(max(a[:, 2].max() - a[:, 0].min(), a[:, 3].max() - a[:, 1].min()))


def find_layers(root: Path, default_crs: str = "EPSG:5186"):
    """축척별·레이어별 SHP 목록과 도엽(폴더) 목록."""
    groups: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() == ".shp" and layer_of(p):
            groups[_group(p, root)].append(p)
    out = {sc: {CONTOUR: [], SPOT: [], BUILDING: []} for sc in SCALES}
    sheets = []
    for g, paths in groups.items():
        sc = next((scale_of(p) for p in paths if scale_of(p)), None)
        sheet = next((sheet_of(p) for p in paths if sheet_of(p)), None) or g
        how = ""
        if sc is None:
            ext = _extent_m(paths, default_crs)
            sc = "1000" if ext < SMALL_SHEET_M else "5000"
            how = f"도엽번호를 못 찾아 자료 범위({ext:.0f} m)로 판단"
        for p in paths:
            out[sc][layer_of(p)].append(p)
        sheets.append({"group": g, "sheet": sheet, "scale": sc, "how": how})
    return out, sheets


def height_field(r) -> str | None:
    """높이가 든 필드 이름. 못 찾으면 None (→ Z 좌표)."""
    names = [f[0] for f in r.fields[1:]]
    upper = {n.upper(): n for n in names}
    for k in HEIGHT_FIELDS:
        if k.upper() in upper:
            return upper[k.upper()]
    return next((n for n in names if any(h in n.upper() for h in HEIGHT_HINTS)), None)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 1 <= f <= 2000 else None  # 캠퍼스 근처에 0 m 이하나 2,000 m 넘는 곳은 없다 → 빈 값으로 본다


def height_of(rec: dict, shape, field: str | None) -> float | None:
    if field is not None:
        h = _num(rec.get(field))
        if h is not None:
            return h
    z = getattr(shape, "z", None)
    if z is not None and len(z):
        return _num(float(np.mean(z)))
    return None


def _first(rec: dict, keys) -> str:
    for k in keys:
        if k in rec and str(rec[k]).strip():
            return str(rec[k]).strip()
    return ""


def densify(pts: np.ndarray, step: float) -> np.ndarray:
    """선을 step m 이하 간격의 점으로."""
    out = [pts[:1]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, math.ceil(float(np.hypot(*(b - a))) / step))
        t = (np.arange(1, n + 1) / n)[:, None]
        out.append(a + (b - a) * t)
    return np.vstack(out)


def read_heights(paths_by_layer: dict[str, list[Path]], work_crs, default_crs: str, step: float,
                 layers=(CONTOUR, SPOT)):
    """등고선 꼭짓점(촘촘히)과 표고점 → (N, 2) 좌표, (N,) 높이, 통계(도형 수·높이 못 읽은 수·쓴 필드)."""
    xy, z = [], []
    stats = {CONTOUR: 0, SPOT: 0, "skipped": 0, "fields": Counter()}
    for code in layers:
        for path in paths_by_layer[code]:
            src = crs_of(path, default_crs)
            r = open_shp(path)
            field = height_field(r)
            stats["fields"][f"{LAYER_NAME[code]}:{field or 'Z 좌표'}"] += 1
            used = 0
            for sr in r.iterShapeRecords():
                h = height_of(sr.record.as_dict(), sr.shape, field)
                pts = np.asarray(sr.shape.points, float)
                if h is None or len(pts) == 0:
                    stats["skipped"] += 1
                    continue
                if code == CONTOUR:
                    parts = list(sr.shape.parts) + [len(pts)]
                    pieces = [densify(pts[parts[k]:parts[k + 1]], step) for k in range(len(parts) - 1)
                              if parts[k + 1] - parts[k] >= 2]
                    if not pieces:
                        stats["skipped"] += 1
                        continue
                    pts = np.vstack(pieces)
                x, y = _to(pts[:, 0], pts[:, 1], src, work_crs)
                xy.append(np.column_stack([x, y]))
                z.append(np.full(len(x), h))
                stats[code] += 1
                used += 1
            if used == 0 and len(r):
                print(f"    ※ {path}: 높이를 하나도 못 읽음. 필드 목록 {[f[0] for f in r.fields[1:]]}")
            r.close()
    if not xy:
        return np.zeros((0, 2)), np.zeros(0), stats
    return np.vstack(xy), np.concatenate(z), stats


def build_dem(xy: np.ndarray, z: np.ndarray, bounds: tuple[float, float, float, float], res: float,
              chunk: int = 400_000):
    """삼각망 선형 보간. bounds = (left, bottom, right, top). 삼각망 밖은 NaN."""
    from rasterio.transform import from_origin
    from scipy.interpolate import LinearNDInterpolator

    key = np.round(xy, 2)
    _, idx, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    zz = np.bincount(inv, weights=z) / np.bincount(inv)  # 같은 점은 평균
    interp = LinearNDInterpolator(xy[idx], zz)
    left, bottom, right, top = bounds
    w, h = int(math.ceil((right - left) / res)), int(math.ceil((top - bottom) / res))
    arr = np.full((h, w), np.nan, dtype="float32")
    xs = left + res * (np.arange(w) + 0.5)
    rows_per = max(1, chunk // w)
    for r0 in range(0, h, rows_per):
        ys = top - res * (np.arange(r0, min(h, r0 + rows_per)) + 0.5)
        gx, gy = np.meshgrid(xs, ys)
        arr[r0:r0 + len(ys)] = interp(gx, gy)
    return arr, from_origin(left, top, res, res)


def write_dem(arr: np.ndarray, transform, crs, path: Path) -> None:
    import rasterio

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1,
                       dtype="float32", crs=crs, transform=transform, nodata=-9999, compress="deflate") as ds:
        ds.write(np.where(np.isnan(arr), -9999, arr).astype("float32"), 1)


def check_points(arr: np.ndarray, transform, xy: np.ndarray, z: np.ndarray) -> dict | None:
    """DEM에 넣지 않은 표고점으로 오차 확인. 격자 칸 가운데 기준 쌍선형 보간."""
    inv = ~transform
    c = inv.a * xy[:, 0] + inv.b * xy[:, 1] + inv.c - 0.5
    r = inv.d * xy[:, 0] + inv.e * xy[:, 1] + inv.f - 0.5
    j0, i0 = np.floor(c).astype(int), np.floor(r).astype(int)
    h, w = arr.shape
    ok = (i0 >= 0) & (j0 >= 0) & (i0 + 1 < h) & (j0 + 1 < w)
    if not ok.any():
        return None
    i0, j0, fr, fc = i0[ok], j0[ok], (r - np.floor(r))[ok], (c - np.floor(c))[ok]
    v = (arr[i0, j0] * (1 - fr) * (1 - fc) + arr[i0, j0 + 1] * (1 - fr) * fc
         + arr[i0 + 1, j0] * fr * (1 - fc) + arr[i0 + 1, j0 + 1] * fr * fc)
    e = v - z[ok]
    e = e[~np.isnan(e)]
    if not len(e):
        return None
    a = np.abs(e)
    return {"n": len(e), "mean": float(e.mean()), "mae": float(a.mean()), "p95": float(np.percentile(a, 95)),
            "max": float(a.max())}


def read_buildings(paths: list[Path], default_crs: str) -> list[dict]:
    feats, seen = [], set()
    for path in paths:
        src = crs_of(path, default_crs)
        sheet = sheet_of(path) or path.parent.name or path.stem
        if sheet in seen:  # 번호를 못 찾아 겹치면 구분
            sheet = f"{sheet}-{len(seen)}"
        seen.add(sheet)
        r = open_shp(path)
        for i, sr in enumerate(r.iterShapeRecords()):
            pts = np.asarray(sr.shape.points, float)
            if len(pts) < 3:
                continue
            parts = list(sr.shape.parts) + [len(pts)]
            rings = [pts[parts[k]:parts[k + 1]] for k in range(len(parts) - 1) if parts[k + 1] - parts[k] >= 3]
            if not rings:
                continue
            ring = max(rings, key=lambda q: abs(float(np.sum(q[:-1, 0] * q[1:, 1] - q[1:, 0] * q[:-1, 1]))))
            lon, lat = _to(ring[:, 0], ring[:, 1], src, "EPSG:4326")
            coords = [[float(a), float(b)] for a, b in zip(lon, lat)]
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            rec = sr.record.as_dict()
            label = _first(rec, LABEL_FIELDS)
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]},
                          "properties": {"fid": f"topo/{sheet}/{i}", "name": label, "ref": ";".join(dong_refs(label)),
                                         "levels": _first(rec, LEVEL_FIELDS), "kind": _first(rec, KIND_FIELDS),
                                         "source": "수치지형도"}})
        r.close()
    return feats


def campus_bounds(lists: list[Path], margin: float) -> tuple[float, float, float, float] | None:
    """건물 좌표 범위 ± margin 도 → (남, 서, 북, 동)."""
    lats, lons = [], []
    for path in lists:
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    lats.append(float(r["lat"]))
                    lons.append(float(r["lon"]))
                except (KeyError, TypeError, ValueError):
                    pass
    if not lats:
        return None
    return (min(lats) - margin, min(lons) - margin, max(lats) + margin, max(lons) + margin)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # cmd에서 로그를 파일로 저장할 때 멈추지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--topo", default=str(TOPO))
    ap.add_argument("--scale", choices=SCALES, default="5000", help="DEM·건물 윤곽을 만들 축척 (기본 5000)")
    ap.add_argument("--res", type=float, default=2.0, help="DEM 격자(m)")
    ap.add_argument("--step", type=float, default=2.0, help="등고선을 점으로 바꿀 간격(m)")
    ap.add_argument("--extent", choices=("data", "campus"), default="data",
                    help="DEM 범위. data = 받은 도엽 전체(도로 그래프까지 덮도록), campus = 건물 좌표 범위 ± --margin")
    ap.add_argument("--margin", type=float, default=0.006, help="--extent campus 일 때 건물 좌표 범위에 더할 여유(도)")
    ap.add_argument("--crs", default="EPSG:5186", help=".prj 가 없을 때 쓸 좌표계")
    ap.add_argument("--buildings", nargs="+", default=[str(p) for p in BUILDING_LISTS])
    ap.add_argument("-o", "--output", default=str(OUT))
    ap.add_argument("--buildings-output", default=str(OUT_BLD))
    args = ap.parse_args(argv)

    from rasterio.warp import transform_bounds

    layers, sheets = find_layers(Path(args.topo), args.crs)
    for sc in SCALES:
        L = layers[sc]
        mine = [s for s in sheets if s["scale"] == sc]
        if not mine:
            continue
        print(f"1:{int(sc):,} 도엽 {len(mine)}개 (SHP 등고선 {len(L[CONTOUR])} · 표고점 {len(L[SPOT])} · 건물 {len(L[BUILDING])}):"
              f" {', '.join(s['sheet'] for s in mine)}")
        for s in mine:
            if s["how"]:
                print(f"  ※ {s['group']}: {s['how']} → 1:{int(sc):,}")
    use = args.scale if layers[args.scale][CONTOUR] else next((sc for sc in SCALES if layers[sc][CONTOUR]), None)
    if use is None:
        raise SystemExit(f"{args.topo} 에 등고선(F0010000) SHP가 없음. 국토정보플랫폼에서 수치지형도 Ver2.0(SHP)을 받아"
                         " 압축 파일마다 폴더를 따로 만들어 풀 것(저장소에는 없다. docs/topo.md)")
    if use != args.scale:
        print(f"※ 1:{int(args.scale):,} 등고선이 없어 1:{int(use):,}로 만든다")
    L = layers[use]
    work = crs_of(L[CONTOUR][0], args.crs)
    has_prj = L[CONTOUR][0].with_suffix(".prj").exists()
    print(f"좌표계: {'EPSG:' + str(work.to_epsg()) if work.to_epsg() else work.to_wkt()[:60]}"
          f" ({'.prj' if has_prj else '--crs 기본값'})")

    xy, z, st = read_heights(L, work, args.crs, args.step)
    print(f"\nDEM: 1:{int(use):,} 등고선 {st[CONTOUR]:,}개 · 표고점 {st[SPOT]:,}개 → 점 {len(z):,}개"
          f" (높이를 못 읽어 뺀 도형 {st['skipped']:,}개)")
    print(f"  높이 필드(파일 수): {dict(st['fields'])}")
    if len(z) < 3:
        raise SystemExit("보간할 점이 모자람")
    bb = campus_bounds([Path(p) for p in args.buildings], args.margin) if args.extent == "campus" else None
    if bb is not None:
        left, bottom, right, top = transform_bounds("EPSG:4326", work, bb[1], bb[0], bb[3], bb[2])
    else:
        (left, bottom), (right, top) = xy.min(axis=0), xy.max(axis=0)
    pad = 300.0  # 가장자리 보간이 끊기지 않게 범위 밖 300 m 점까지 쓴다
    keep = (xy[:, 0] > left - pad) & (xy[:, 0] < right + pad) & (xy[:, 1] > bottom - pad) & (xy[:, 1] < top + pad)
    if keep.sum() < 3:
        raise SystemExit("캠퍼스 범위에 등고선·표고점이 없음. 도엽을 확인할 것")
    print(f"  높이 {z[keep].min():.1f}~{z[keep].max():.1f} m, 쓴 점 {int(keep.sum()):,}개")
    arr, transform = build_dem(xy[keep], z[keep], (left, bottom, right, top), args.res)
    out = Path(args.output)
    write_dem(arr, transform, work, out)
    print(f"  저장: {out} ({arr.shape[1]}×{arr.shape[0]}칸, {args.res:g} m 격자, 빈 칸 {float(np.isnan(arr).mean()):.1%})")

    for sc in SCALES:  # 다른 축척의 표고점 = 독립 검증점
        if sc == use or not layers[sc][SPOT]:
            continue
        cxy, cz, _ = read_heights(layers[sc], work, args.crs, args.step, layers=(SPOT,))
        chk = check_points(arr, transform, cxy, cz) if len(cz) else None
        if chk:
            print(f"  검증: DEM에 넣지 않은 1:{int(sc):,} 표고점 {chk['n']}개에서 오차 평균 {chk['mean']:+.2f} m,"
                  f" 평균 절대오차 {chk['mae']:.2f} m, 95% {chk['p95']:.2f} m 이내, 최대 {chk['max']:.2f} m")

    feats = read_buildings(L[BUILDING], args.crs)
    bout = Path(args.buildings_output)
    bout.parent.mkdir(parents=True, exist_ok=True)
    bout.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    named = sum(1 for f in feats if f["properties"]["ref"])
    print(f"\n저장: {bout} (1:{int(use):,} 건물 윤곽 {len(feats):,}개, 주기에 동 번호가 있는 윤곽 {named:,}개)")
    if not has_prj:
        print("  ※ .prj 가 없어 EPSG:5186 으로 가정했다. 결과 고도가 상식과 다르면 --crs 를 바꿔 다시 실행")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
