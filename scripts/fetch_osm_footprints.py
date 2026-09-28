"""OpenStreetMap에서 관악캠퍼스 건물 윤곽·출입구·보행로를 받아 GeoJSON으로 저장한다.

  python scripts/fetch_osm_footprints.py
  python scripts/fetch_osm_footprints.py --bbox 37.443,126.938,37.472,126.967   # 남,서,북,동

- Overpass API 1회 요청. 결과
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
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "osm_buildings.geojson"
OUT_ENT = ROOT / "data" / "osm_entrances.geojson"
OUT_PATHS = ROOT / "data" / "osm_paths.geojson"
CAMPUS = ROOT / "data" / "campus_buildings.csv"
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
DEFAULT_BBOX = (37.443, 126.938, 37.472, 126.967)  # 남, 서, 북, 동
QUERY = """[out:json][timeout:180];
(
  way["building"]({s},{w},{n},{e});
  relation["building"]({s},{w},{n},{e});
);
out body geom;
node["entrance"]({s},{w},{n},{e});
out body;
way["highway"]({s},{w},{n},{e});
out body geom;"""
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", help="남,서,북,동 (위도·경도)")
    args = ap.parse_args()
    s, w, n, e = [float(v) for v in args.bbox.split(",")] if args.bbox else bbox_from_campus()
    query = QUERY.format(s=s, w=w, n=n, e=e)
    print(f"범위 남 {s:.4f} 서 {w:.4f} 북 {n:.4f} 동 {e:.4f}")

    data = None
    for url in ENDPOINTS:
        try:
            r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=240)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as ex:
            print(f"  {url}: 실패 {ex}")
    if data is None:
        raise SystemExit("Overpass 서버 두 곳 모두 실패. 잠시 뒤 다시 실행")

    feats, ents, paths = to_features(data), to_entrances(data), to_paths(data)
    _save(OUT, feats)
    _save(OUT_ENT, ents)
    _save(OUT_PATHS, paths)
    named = sum(1 for f in feats if f["properties"]["name"])
    reffed = sum(1 for f in feats if f["properties"]["ref"])
    print(f"저장: {OUT} (건물 윤곽 {len(feats)}개, 이름 있음 {named}, ref 있음 {reffed})")
    print(f"저장: {OUT_ENT} (출입구 노드 {len(ents)}개, {dict(Counter(f['properties']['entrance'] for f in ents))})")
    print(f"저장: {OUT_PATHS} (길 {len(paths)}개, {dict(Counter(f['properties']['highway'] for f in paths).most_common(8))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
