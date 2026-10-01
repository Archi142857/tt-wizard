"""OpenStreetMap에서 바탕 지도(scripts/basemap.py)에 쓸 숲·잔디·공원 면과 길 선을 받아 data/osm_basemap.geojson 으로 저장한다.

  python scripts/fetch_osm_basemap.py                                   # 범위: 수치지형도 도엽 네 장
  python scripts/fetch_osm_basemap.py --bbox 37.425,126.925,37.475,126.975   # 남,서,북,동

- 인터넷이 되는 PC 에서 돌린다(클라우드 작업 공간에서는 OSM 서버가 막혀 있다). 받은 파일을 커밋하고
  python scripts/basemap.py 를 다시 돌리면 초록(숲·잔디)이 어림 대신 이 면으로 칠해진다
- 한 번에 다 받으면 서버가 504(시간 초과)를 내서 다섯 번으로 나눠 받는다(10/1 사용자 PC 에서 504):
    면: landuse·natural·leisure 태그마다(basemap.GREEN_KIND)  — way 와 multipolygon relation(outer·inner 조각을 이어 고리로)
    선: 큰길·보행로·계단은 범위 전체, 동네 찻길(service·residential …)은 캠퍼스 둘레만(basemap.py 도 캠퍼스 둘레만 그린다)
- 서버를 돌아가며 요청하고, 다 안 되면 쉬었다 다시(세 바퀴). 서버가 200 으로 답해도 '시간 초과' 표시(remark)가 있으면 실패로 본다.
  받은 조각은 임시 폴더에 두고, 다시 돌리면 받은 조각은 건너뛴다(하루 동안). 다 받으면 합쳐 저장하고 조각을 지운다
- 데이터 © OpenStreetMap contributors (ODbL)
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from basemap import GREEN_KIND  # noqa: E402

OUT = ROOT / "data" / "osm_basemap.geojson"
PARTS = Path(tempfile.gettempdir()) / "ttw_osm_basemap"
BBOX = (37.425, 126.925, 37.475, 126.975)  # 남, 서, 북, 동 — 수치지형도 37612018·019·028·029
NEAR_MARGIN = 0.008  # 동네 찻길을 받을 캠퍼스 둘레(도, 약 700~900 m). basemap.py 의 '가까이'(캠퍼스 땅 + 400 m)를 덮는다
TAGS = sorted({k for k, _ in GREEN_KIND})
WIDE_HIGHWAY = "^((motorway|trunk|primary|secondary)(_link)?|footway|path|steps|pedestrian|track|cycleway|bridleway)$"
NEAR_HIGHWAY = "^(tertiary|tertiary_link|unclassified|residential|service|living_street)$"
HEAD = "[out:json][timeout:180];"


def area_queries(bb: str) -> list[tuple[str, str]]:
    out = []
    for key in TAGS:
        vals = "|".join(sorted(v for k, v in GREEN_KIND if k == key))
        out.append((f"면 {key}", f'{HEAD}(way["{key}"~"^({vals})$"]({bb});'
                                  f'relation["{key}"~"^({vals})$"]["type"="multipolygon"]({bb}););out body geom;'))
    return out


def line_queries(bb: str, near: str) -> list[tuple[str, str]]:
    return [("선 큰길·보행로", f'{HEAD}way["highway"~"{WIDE_HIGHWAY}"]({bb});out body geom;'),
            ("선 캠퍼스 둘레 찻길", f'{HEAD}way["highway"~"{NEAR_HIGHWAY}"]({near});out body geom;')]


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


def overpass(query: str, rounds: int = 3, wait: float = 20.0) -> dict | None:
    """서버를 돌아가며 요청. 다 안 되면 wait·2wait 초 쉬고 다시. 끝내 안 되면 None."""
    import requests

    from fetch_osm_footprints import ENDPOINTS, HEADERS

    for r in range(rounds):
        for url in ENDPOINTS:
            host, t0 = url.split("/")[2], time.time()
            try:
                res = requests.post(url, data={"data": query}, headers=HEADERS, timeout=(15, 240))
                res.raise_for_status()
                data = res.json()
                remark = str(data.get("remark") or "")
                if "error" in remark.lower():  # 시간·메모리 초과면 200 으로 답하면서 결과를 잘라 보낸다
                    raise RuntimeError(remark[:80])
                print(f"    {host}: {time.time() - t0:.0f}초")
                return data
            except Exception as ex:
                print(f"    {host}: {type(ex).__name__} {str(ex)[:70]} ({time.time() - t0:.0f}초)")
        if r + 1 < rounds:
            print(f"    {wait * (r + 1):.0f}초 쉬고 다시")
            time.sleep(wait * (r + 1))
    return None


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    from fetch_osm_footprints import bbox_from_campus

    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", help="남,서,북,동 (위도·경도)")
    args = ap.parse_args()
    s, w, n, e = [float(v) for v in args.bbox.split(",")] if args.bbox else BBOX
    bb = f"{s},{w},{n},{e}"
    ns, nw, nn, ne = bbox_from_campus(NEAR_MARGIN)
    near = f"{max(s, ns)},{max(w, nw)},{min(n, nn)},{min(e, ne)}"
    print(f"범위 남 {s} 서 {w} 북 {n} 동 {e} (동네 찻길은 캠퍼스 둘레 {near})")
    PARTS.mkdir(parents=True, exist_ok=True)
    jobs = [(label, q, to_areas) for label, q in area_queries(bb)] + [(label, q, to_lines) for label, q in line_queries(bb, near)]
    feats, failed = [], []
    for i, (label, query, parse) in enumerate(jobs):
        part = PARTS / f"{i}.json"
        if part.exists() and time.time() - part.stat().st_mtime < 86400 and json.loads(part.read_text(encoding="utf-8")).get("q") == query:
            got = json.loads(part.read_text(encoding="utf-8"))["features"]
            print(f"  {label}: 전에 받은 것 {len(got)}개")
        else:
            print(f"  {label} 요청")
            data = overpass(query)
            if data is None:
                failed.append(label)
                print(f"  {label}: 실패")
                continue
            got = parse(data)
            part.write_text(json.dumps({"q": query, "features": got}, ensure_ascii=False), encoding="utf-8")
            key = "kind" if parse is to_areas else "highway"
            print(f"  {label} {len(got)}개 {dict(Counter(f['properties'][key] for f in got).most_common(6))}")
        feats += got
    if failed:
        print(f"실패: {failed} → 몇 분 뒤 다시 실행(받은 조각은 건너뛴다). 기존 {OUT.name} 은 그대로 둔다")
        return 1
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    for p in PARTS.glob("*.json"):
        p.unlink()
    print(f"저장: {OUT} ({OUT.stat().st_size / 1e6:.1f} MB) → python scripts/basemap.py 로 바탕 지도를 다시 만든다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
