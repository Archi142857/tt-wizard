"""OpenStreetMap에서 관악캠퍼스 건물 윤곽·출입구·보행로를 받아 GeoJSON으로 저장한다.

  python scripts/fetch_osm_footprints.py
  python scripts/fetch_osm_footprints.py --bbox 37.443,126.938,37.472,126.967   # 남,서,북,동

- Overpass API에 건물·출입구·길을 따로 3번 요청한다(서버가 바쁘면 다른 서버로, 그래도 안 되면 잠시 쉬고 다시). 결과
    data/osm_buildings.geojson   건물 윤곽 Polygon (osm_type, osm_id, part, name, ref, levels, building, nodes)
    data/osm_entrances.geojson   entrance 태그가 붙은 노드 Point (entrance, level, name, ref, door, wheelchair, access)
    data/osm_paths.geojson       highway 선 LineString (highway, bridge, tunnel, indoor, layer, level, covered, nodes)
- building_elevation.py 가 건물 둘레 지면 고도(윤곽)와 지상 출입구 위치(출입구 노드·보행로 접점)를 뽑는 데 쓴다
- 범위를 안 주면 data/campus_buildings.csv 좌표 범위에 여유를 두어 정한다
- 데이터 © OpenStreetMap contributors (ODbL). 이 자료로 만든 결과를 넘길 때 출처를 적는다
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "osm_buildings.geojson"
OUT_ENT = ROOT / "data" / "osm_entrances.geojson"
OUT_PATHS = ROOT / "data" / "osm_paths.geojson"
CAMPUS = ROOT / "data" / "campus_buildings.csv"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
DEFAULT_BBOX = (37.443, 126.938, 37.472, 126.967)  # 남, 서, 북, 동
QUERIES = {  # 한 번에 다 받으면 서버가 504(시간 초과)를 낼 때가 있어 셋으로 나눈다
    "buildings": '[out:json][timeout:90];(way["building"]({bb});relation["building"]({bb}););out body geom;',
    "entrances": '[out:json][timeout:60];node["entrance"]({bb});out body;',
    "paths": '[out:json][timeout:90];way["highway"]({bb});out body geom;',
}
HEADERS = {"User-Agent": "tt-wizard/0.1 (student project; one-off download)"}

Point = tuple[float, float]  # (lon, lat)


def assemble_rings(parts: list[list[Point]]) -> list[list[Point]]:
    """멀티폴리곤의 outer 조각(way)들을 끝점끼리 이어 닫힌 고리로 만든다."""
    parts = [list(p) for p in parts if len(p) >= 2]
    rings: list[list[Point]] = []
    while parts:
        cur = parts.pop(0)
        joined = True
        while cur[0] != cur[-1] and joined:
            joined = False
            for i, p in enumerate(parts):
                if p[0] == cur[-1]:
                    cur = cur + p[1:]
                elif p[-1] == cur[-1]:
                    cur = cur + p[::-1][1:]
                elif p[-1] == cur[0]:
                    cur = p + cur[1:]
                elif p[0] == cur[0]:
                    cur = p[::-1] + cur[1:]
                else:
                    continue
                parts.pop(i)
                joined = True
                break
        if cur[0] == cur[-1] and len(cur) >= 4:
            rings.append(cur)
    return rings


def _way_coords(el: dict) -> tuple[list[Point], list[int]]:
    """way 좌표와 노드 id. 좌표가 빠진 노드가 있으면 id 목록은 버린다(순서가 어긋나므로)."""
    geom = el.get("geometry") or []
    coords = [(p["lon"], p["lat"]) for p in geom if p]
    nodes = el.get("nodes") or []
    if len(coords) != len(geom) or len(nodes) != len(coords):
        nodes = []
    return coords, nodes


def to_features(data: dict) -> list[dict]:
    """건물 윤곽."""
    feats = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if "building" not in tags:
            continue
        nodes: list[int] = []
        if el.get("type") == "way":
            ring, nodes = _way_coords(el)
            if len(ring) >= 3 and ring[0] != ring[-1]:
                ring.append(ring[0])
                nodes = nodes + nodes[:1] if nodes else nodes
            rings = [ring] if len(ring) >= 4 else []
        elif el.get("type") == "relation":
            outer = [[(p["lon"], p["lat"]) for p in m.get("geometry") or [] if p]
                     for m in el.get("members", []) if m.get("type") == "way" and m.get("role") == "outer"]
            rings = assemble_rings(outer)
        else:
            continue
        for k, ring in enumerate(rings):
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[x, y] for x, y in ring]]},
                "properties": {
                    "osm_type": el["type"], "osm_id": el["id"], "part": k,
                    "name": tags.get("name", ""), "ref": tags.get("ref", ""),
                    "levels": tags.get("building:levels", ""), "building": tags.get("building", ""),
                    "nodes": nodes,
                },
            })
    return feats


def to_entrances(data: dict) -> list[dict]:
    feats = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if el.get("type") != "node" or "entrance" not in tags or "lat" not in el:
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
            "properties": {"osm_id": el["id"], **{k: tags.get(k, "") for k in
                           ("entrance", "level", "name", "ref", "door", "wheelchair", "access")}},
        })
    return feats


def to_paths(data: dict) -> list[dict]:
    feats = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if el.get("type") != "way" or "highway" not in tags:
            continue
        coords, nodes = _way_coords(el)
        if len(coords) < 2:
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[x, y] for x, y in coords]},
            "properties": {"osm_id": el["id"], **{k: tags.get(k, "") for k in
                           ("highway", "name", "bridge", "tunnel", "indoor", "layer", "level", "covered")},
                           "nodes": nodes},
        })
    return feats


def bbox_from_campus(margin: float = 0.003) -> tuple[float, float, float, float]:
    if not CAMPUS.exists():
        return DEFAULT_BBOX
    lats, lons = [], []
    with open(CAMPUS, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("lat") and r.get("lon"):
                lats.append(float(r["lat"]))
                lons.append(float(r["lon"]))
    if not lats:
        return DEFAULT_BBOX
    return (min(lats) - margin, min(lons) - margin, max(lats) + margin, max(lons) + margin)


def _save(path: Path, feats: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")


def overpass(query: str, tries: int = 3, wait: float = 20.0) -> dict | None:
    """서버를 돌아가며 요청. 모두 실패하면 wait·2wait 초 쉬고 다시. 끝내 안 되면 None."""
    for attempt in range(tries):
        for url in ENDPOINTS:
            try:
                r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=150)
                r.raise_for_status()
                return r.json()
            except Exception as ex:
                print(f"    {url.split('/')[2]}: {type(ex).__name__} {str(ex)[:70]}")
        if attempt + 1 < tries:
            print(f"    {wait * (attempt + 1):.0f}초 쉬고 다시")
            time.sleep(wait * (attempt + 1))
    return None


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # cmd에서 로그를 파일로 저장할 때 멈추지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", help="남,서,북,동 (위도·경도)")
    args = ap.parse_args()
    s, w, n, e = [float(v) for v in args.bbox.split(",")] if args.bbox else bbox_from_campus()
    bb = f"{s},{w},{n},{e}"
    print(f"범위 남 {s:.4f} 서 {w:.4f} 북 {n:.4f} 동 {e:.4f}")

    failed = []
    for key, out, parse, label in (("buildings", OUT, to_features, "건물 윤곽"),
                                   ("entrances", OUT_ENT, to_entrances, "출입구 노드"),
                                   ("paths", OUT_PATHS, to_paths, "길")):
        print(f"  {label} 요청")
        data = overpass(QUERIES[key].format(bb=bb))
        if data is None:
            failed.append(label)
            print(f"  {label}: 실패 (기존 파일은 그대로 둔다)")
            continue
        feats = parse(data)
        _save(out, feats)
        if key == "buildings":
            named = sum(1 for f in feats if f["properties"]["name"])
            reffed = sum(1 for f in feats if f["properties"]["ref"])
            print(f"저장: {out} ({label} {len(feats)}개, 이름 있음 {named}, ref 있음 {reffed})")
        elif key == "entrances":
            print(f"저장: {out} ({label} {len(feats)}개, {dict(Counter(f['properties']['entrance'] for f in feats))})")
        else:
            print(f"저장: {out} ({label} {len(feats)}개, {dict(Counter(f['properties']['highway'] for f in feats).most_common(8))})")
    if failed:
        print(f"실패: {failed} → 몇 분 뒤 다시 실행")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
