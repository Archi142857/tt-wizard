"""OpenStreetMap에서 바탕 지도(scripts/basemap.py)에 쓸 숲·잔디·공원 면과 길 선을 받아 data/osm_basemap.geojson 으로 저장한다.

  python scripts/fetch_osm_basemap.py                                   # 범위: 수치지형도 도엽 네 장
  python scripts/fetch_osm_basemap.py --bbox 37.425,126.925,37.475,126.975   # 남,서,북,동

- 인터넷이 되는 PC 에서 돌린다(클라우드 작업 공간에서는 OSM 서버가 막혀 있다). 받은 파일을 커밋하고
  python scripts/basemap.py 를 다시 돌리면 초록(숲·잔디)이 어림 대신 이 면으로 칠해진다
- 면(Polygon·MultiPolygon, properties.kind = green·park·grass·pitch): basemap.GREEN_KIND 의 태그.
  way 와 multipolygon relation(outer·inner 조각을 이어 고리로)
- 선(LineString): highway 전부. basemap.py 가 큰길 등급·캠퍼스 안 길·보행로·계단으로 나눈다
- 서버 요청은 면·선 두 번(fetch_osm_footprints.py 의 overpass: 서버를 돌아가며, 실패하면 쉬고 다시)
- 데이터 © OpenStreetMap contributors (ODbL)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from basemap import GREEN_KIND  # noqa: E402

OUT = ROOT / "data" / "osm_basemap.geojson"
BBOX = (37.425, 126.925, 37.475, 126.975)  # 남, 서, 북, 동 — 수치지형도 37612018·019·028·029
TAGS = sorted({k for k, _ in GREEN_KIND})


def area_query(bb: str) -> str:
    parts = []
    for key in TAGS:
        vals = "|".join(sorted(v for k, v in GREEN_KIND if k == key))
        parts.append(f'way["{key}"~"^({vals})$"]({bb});relation["{key}"~"^({vals})$"]["type"="multipolygon"]({bb});')
    return f'[out:json][timeout:120];({"".join(parts)});out body geom;'


def line_query(bb: str) -> str:
    return f'[out:json][timeout:120];way["highway"]({bb});out body geom;'


def _inside(pt, ring) -> bool:
    x, y = pt
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def kind_of(tags: dict) -> str | None:
    return next((GREEN_KIND[(k, v)] for k, v in GREEN_KIND if tags.get(k) == v), None)


def to_areas(data: dict) -> list[dict]:
    """숲·잔디·공원 면. relation 은 outer 고리마다 그 안에 든 inner 고리를 구멍으로 붙인다."""
    from fetch_osm_footprints import assemble_rings

    feats = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        kind = kind_of(tags)
        if not kind:
            continue
        if el.get("type") == "way":
            ring = [(p["lon"], p["lat"]) for p in el.get("geometry") or [] if p]
            if len(ring) >= 3 and ring[0] != ring[-1]:
                continue  # 닫히지 않은 way 는 면이 아니다(선으로 그린 경계 등)
            polys = [[ring]] if len(ring) >= 4 else []
        elif el.get("type") == "relation":
            def parts(role):
                return [[(p["lon"], p["lat"]) for p in m.get("geometry") or [] if p]
                        for m in el.get("members", []) if m.get("type") == "way" and (m.get("role") or "outer") == role]
            outers, inners = assemble_rings(parts("outer")), assemble_rings(parts("inner"))
            polys = [[o] + [i for i in inners if _inside(i[0], o)] for o in outers]
        else:
            continue
        if not polys:
            continue
        geom = ({"type": "Polygon", "coordinates": [[[x, y] for x, y in r] for r in polys[0]]} if len(polys) == 1 else
                {"type": "MultiPolygon", "coordinates": [[[[x, y] for x, y in r] for r in p] for p in polys]})
        feats.append({"type": "Feature", "geometry": geom,
                      "properties": {"kind": kind, "osm_type": el["type"], "osm_id": el["id"],
                                     **{k: tags[k] for k in TAGS if k in tags}, "name": tags.get("name", "")}})
    return feats


def to_lines(data: dict) -> list[dict]:
    from fetch_osm_footprints import to_paths

    feats = to_paths(data)
    for f in feats:
        f["properties"].pop("nodes", None)  # 바탕 지도에는 노드 번호가 필요 없다(파일만 커진다)
    return feats


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    from fetch_osm_footprints import overpass

    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", help="남,서,북,동 (위도·경도)")
    args = ap.parse_args()
    s, w, n, e = [float(v) for v in args.bbox.split(",")] if args.bbox else BBOX
    bb = f"{s},{w},{n},{e}"
    print(f"범위 남 {s} 서 {w} 북 {n} 동 {e}")
    feats = []
    for label, query, parse in (("숲·잔디·공원 면", area_query(bb), to_areas), ("길", line_query(bb), to_lines)):
        print(f"  {label} 요청")
        data = overpass(query)
        if data is None:
            print(f"  {label}: 실패 → 몇 분 뒤 다시 실행 (기존 파일은 그대로 둔다)")
            return 1
        got = parse(data)
        key = "kind" if parse is to_areas else "highway"
        print(f"  {label} {len(got)}개 {dict(Counter(f['properties'][key] for f in got).most_common(8))}")
        feats += got
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    print(f"저장: {OUT} → python scripts/basemap.py 로 바탕 지도를 다시 만든다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
