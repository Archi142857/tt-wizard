"""TMAP 보행자 경로 API로 건물 간 도보 시간을 채운다 ('캠퍼스 마법 지도' 데이터를 못 받았을 때의 대안).

  POST https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1
  headers: appKey, Content-Type: application/json
  body: startX(경도), startY(위도), endX, endY, startName, endName
  응답: features[0].properties.totalDistance (m), totalTime (초)

무료 제공량이 경로탐색 일 1,000건 수준이라(요금 페이지 확인 필요) 실행당 호출 수를 --limit 로 제한하고,
이미 travel.csv 에 있는 쌍은 건너뛰어 여러 날에 나눠 채울 수 있게 했다.

사용법
  set TMAP_APP_KEY=...  (또는 .env)
  python scripts/tmap_matrix.py --test                # 대표 5쌍만 조회해 화면에 출력
  python scripts/tmap_matrix.py --limit 900           # 빠진 쌍을 900개까지 채움 (대칭: i<j만)
  python scripts/tmap_matrix.py --directed --limit 900 # 오르막/내리막 구분 (양방향)
"""

from __future__ import annotations

import argparse
import csv
import itertools
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ttwizard.travel import load_buildings  # noqa: E402

URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1"
BUILDINGS = ROOT / "data" / "buildings.csv"
TRAVEL = ROOT / "data" / "travel.csv"
TEST_PAIRS = [("200", "301"), ("504", "83"), ("919", "200"), ("302", "500"), ("GATE", "301")]


def load_env_key() -> str:
    key = os.environ.get("TMAP_APP_KEY", "")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("TMAP_APP_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    if not key:
        sys.exit("TMAP_APP_KEY 가 없습니다. .env 에 TMAP_APP_KEY=... 를 넣으세요 (커밋 금지).")
    return key


def route_minutes(key: str, a, b) -> tuple[float, float]:
    body = {
        "startX": str(a.lon), "startY": str(a.lat), "endX": str(b.lon), "endY": str(b.lat),
        "startName": a.id, "endName": b.id, "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
    }
    r = requests.post(URL, json=body, headers={"appKey": key, "Content-Type": "application/json"}, timeout=30)
    r.raise_for_status()
    props = r.json()["features"][0]["properties"]
    return props["totalTime"] / 60.0, props["totalDistance"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--limit", type=int, default=900)
    ap.add_argument("--directed", action="store_true", help="양방향 모두 조회 (기본은 i<j 한 방향)")
    ap.add_argument("--sleep", type=float, default=0.2)
    args = ap.parse_args()

    key = load_env_key()
    bl = load_buildings(BUILDINGS)
    ids = [b for b in bl if bl[b].lat is not None]

    if args.test:
        for a, b in TEST_PAIRS:
            if a in bl and b in bl:
                m, d = route_minutes(key, bl[a], bl[b])
                print(f"{a} → {b}: {m:.1f}분, {d:.0f}m")
        return 0

    done: set[tuple[str, str]] = set()
    rows: list[dict] = []
    if TRAVEL.exists():
        with open(TRAVEL, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
                done.add((row["from"], row["to"]))

    pairs = list(itertools.permutations(ids, 2)) if args.directed else list(itertools.combinations(ids, 2))
    todo = [p for p in pairs if p not in done and (args.directed or (p[1], p[0]) not in done)]
    print(f"건물 {len(ids)}개, 전체 쌍 {len(pairs)}개, 남은 쌍 {len(todo)}개, 이번 실행 최대 {args.limit}개")

    n = 0
    try:
        for a, b in todo[: args.limit]:
            m, d = route_minutes(key, bl[a], bl[b])
            rows.append({"from": a, "to": b, "minutes": f"{m:.1f}", "source": "tmap"})
            n += 1
            time.sleep(args.sleep)
    except Exception as e:
        print(f"중단: {e} — 지금까지 {n}개 저장")
    with open(TRAVEL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["from", "to", "minutes", "source"])
        w.writeheader()
        w.writerows(rows)
    print(f"저장: {TRAVEL} (+{n}개, 총 {len(rows)}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
