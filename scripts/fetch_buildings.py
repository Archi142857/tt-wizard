"""동 번호 → 위경도. 서울대 캠퍼스맵 검색 API를 쓴다 (SNUTT LectureBuildingService와 같은 방식).

  GET https://map.snu.ac.kr/api/search.action?lang_type=KOR&search_word=301
  → {"search_list": [{"name": "...", "vil_dong_nm": "301", "lat_val": 37.44.., "lon_val": 126.95.., "con_type": "F", "fac_type": "OTHER", ...}]}

후보 중 con_type == "F", fac_type == "OTHER", vil_dong_nm == 동번호 인 것을 고르고, 여럿이면 이름이 짧은 것.

사용법
  python scripts/fetch_buildings.py                       # data/lectures.json 의 모든 동
  python scripts/fetch_buildings.py --history             # data/buildings_history.csv (과거 학기 포함) 의 모든 동
  python scripts/fetch_buildings.py 200 301 302 500 504   # 지정한 동만
기존 data/buildings.csv 의 행(GATE, 919 같은 수동 항목 포함)은 유지하고, 새 동만 추가한다.

※ 학교 API라 사용 조건을 한 번 확인할 것. 실행당 요청은 동 개수만큼(수십 회)이고 학기당 한 번이면 충분하다.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ttwizard.parse_sugang import sections_from_json  # noqa: E402

URL = "https://map.snu.ac.kr/api/search.action"
HEADERS = {
    "User-Agent": "Mozilla/5.0 tt-wizard/0.1 (student project; low volume)",
    "Referer": "https://map.snu.ac.kr/web/main.action",
}
BUILDINGS = ROOT / "data" / "buildings.csv"
LECTURES = ROOT / "data" / "lectures.json"
HISTORY = ROOT / "data" / "buildings_history.csv"


def lookup(session: requests.Session, building: str) -> dict | None:
    r = session.get(URL, params={"lang_type": "KOR", "search_word": building}, timeout=30)
    r.raise_for_status()
    items = r.json().get("search_list", [])
    cands = [i for i in items if i.get("con_type") == "F" and i.get("fac_type") == "OTHER" and str(i.get("vil_dong_nm")) == building]
    if not cands:
        return None
    best = min(cands, key=lambda i: len(i.get("name", "")))
    lat, lon = float(best["lat_val"]), float(best["lon_val"])
    if not (37.40 < lat < 37.52 and 126.90 < lon < 127.02):  # 관악 범위 밖이면 다른 필드일 수 있음
        lat, lon = float(best.get("lat_val1", lat)), float(best.get("lon_val1", lon))
    return {"building": building, "name": f"{best.get('name', '')}({building}동)", "lat": lat, "lon": lon}


def main(argv: list[str]) -> int:
    existing: dict[str, dict] = {}
    if BUILDINGS.exists():
        with open(BUILDINGS, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["building"]] = row

    if argv == ["--history"]:
        with open(HISTORY, newline="", encoding="utf-8") as f:
            wanted = [row["building"] for row in csv.DictReader(f)]
    elif argv:
        wanted = argv
    else:
        secs = sections_from_json(LECTURES)
        wanted = sorted({b for s in secs for b in s.buildings}, key=lambda x: (len(x), x))
    todo = [b for b in wanted if b not in existing]
    print(f"조회할 동: {len(todo)}개 (이미 있음 {len(wanted) - len(todo)}개)")

    s = requests.Session()
    s.headers.update(HEADERS)
    missing = []
    for b in todo:
        try:
            hit = lookup(s, b)
        except Exception as e:
            print(f"  {b}: 오류 {e}")
            hit = None
        if hit:
            existing[b] = {k: str(v) for k, v in hit.items()}
            print(f"  {b}: {hit['name']} ({hit['lat']:.5f}, {hit['lon']:.5f})")
        else:
            missing.append(b)
            print(f"  {b}: 못 찾음 — 수동으로 채울 것")
        time.sleep(0.3)

    BUILDINGS.parent.mkdir(exist_ok=True)
    with open(BUILDINGS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["building", "name", "lat", "lon"])
        w.writeheader()
        for b in sorted(existing, key=lambda x: (not x.isdigit(), len(x), x)):
            row = existing[b]
            w.writerow({k: row.get(k, "") for k in w.fieldnames})
    print(f"저장: {BUILDINGS} ({len(existing)}개). 못 찾은 동: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
