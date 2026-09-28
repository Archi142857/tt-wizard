"""서울대 캠퍼스맵에 동 번호가 있는 건물을 모두 모은다 (강의가 없는 연구동·기숙사·편의시설 포함).

  python scripts/fetch_campus_buildings.py              # 1~999번을 차례로 검색
  python scripts/fetch_campus_buildings.py --max 120    # 범위를 줄여 시험

캠퍼스맵 검색 API(fetch_buildings.py 와 같은 주소)는 이름이나 동 번호에 검색어가 들어간 항목을 돌려준다.
번호마다 한 번씩 검색해 시설(con_type F) 가운데 동 번호(vil_dong_nm)가 있는 항목을 모두 모은다.
43-1, 43-2 처럼 가지 번호가 붙은 동은 43 검색 결과에 함께 나온다.

- 응답은 data/raw/campusmap/<번호>.json 에 저장하고, 다시 돌리면 저장본을 쓴다 (끊겨도 이어서 실행)
- 요청 사이 --sleep 초(기본 0.5) 쉰다. 999번이면 10분 남짓. 학교 서버이니 한 번 받으면 다시 돌리지 않는다
- 결과: data/campus_buildings.csv — building, name, ename, fac_type, lat, lon
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
URL = "https://map.snu.ac.kr/api/search.action"
HEADERS = {
    "User-Agent": "Mozilla/5.0 tt-wizard/0.1 (student project; low volume)",
    "Referer": "https://map.snu.ac.kr/web/main.action",
}
RAW = ROOT / "data" / "raw" / "campusmap"
OUT = ROOT / "data" / "campus_buildings.csv"
FIELDS = ["building", "name", "ename", "fac_type", "lat", "lon"]


def building_key(b: str):
    """'43-2' → (0, 43, 2): 숫자 동을 번호순으로, 그 밖(GATE 등)은 뒤로."""
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", b)
    if m:
        return (0, int(m.group(1)), int(m.group(2) or 0), b)
    return (1, 0, 0, b)


def _coord(item: dict) -> tuple[float, float] | None:
    try:
        lat, lon = float(item.get("lat_val")), float(item.get("lon_val"))
    except (TypeError, ValueError):
        return None
    if 37.40 < lat < 37.52 and 126.90 < lon < 127.02:  # 관악 범위 밖이면 버린다
        return lat, lon
    return None


def _rank(row: dict) -> tuple:
    # 같은 동이 여러 항목으로 나오면: 좌표 있음 > 건물(OTHER) > 이름이 짧은 것
    return (bool(row["lat"]), row["fac_type"] == "OTHER", -len(row["name"]))


def merge_items(found: dict[str, dict], data: dict | None) -> None:
    """검색 응답 하나에서 동 번호가 있는 시설을 found 에 더한다."""
    for it in (data or {}).get("search_list") or []:
        if it.get("con_type") != "F":
            continue
        b = str(it.get("vil_dong_nm") or "").strip()
        if not b or b.lower() in ("null", "none"):
            continue
        c = _coord(it)
        row = {
            "building": b,
            "name": str(it.get("name") or "").strip(),
            "ename": str(it.get("ename") or "").strip(),
            "fac_type": str(it.get("fac_type") or ""),
            "lat": f"{c[0]:.6f}" if c else "",
            "lon": f"{c[1]:.6f}" if c else "",
        }
        old = found.get(b)
        if old is None or _rank(row) > _rank(old):
            found[b] = row


def fetch(session: requests.Session, n: int, refresh: bool, sleep: float) -> tuple[dict, bool]:
    path = RAW / f"{n}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8")), False
    r = session.get(URL, params={"lang_type": "KOR", "search_word": str(n)}, timeout=30)
    r.raise_for_status()
    data = r.json()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(sleep)
    return data, True


def write_csv(found: dict[str, dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for b in sorted(found, key=building_key):
            w.writerow(found[b])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--max", type=int, default=999)
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--refresh", action="store_true", help="저장본을 무시하고 다시 받기")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update(HEADERS)
    found: dict[str, dict] = {}
    failed: list[int] = []
    requested = 0
    for n in range(args.start, args.max + 1):
        try:
            data, net = fetch(s, n, args.refresh, args.sleep)
        except Exception as e:  # 네트워크 오류는 건너뛰고 다음 실행 때 다시 받는다
            print(f"  {n}: 오류 {e}")
            failed.append(n)
            time.sleep(args.sleep)
            continue
        requested += net
        merge_items(found, data)
        if n % 50 == 0:
            print(f"  {n}/{args.max} 검색 · 새 요청 {requested}회 · 지금까지 건물 {len(found)}개")

    write_csv(found, OUT)
    no_coord = [b for b in sorted(found, key=building_key) if not found[b]["lat"]]
    kinds = Counter(r["fac_type"] for r in found.values())
    print(f"\n저장: {OUT} (건물 {len(found)}개, 새 요청 {requested}회)")
    print(f"  fac_type: {dict(kinds)}")
    print(f"  좌표 없음: {no_coord or '없음'}")
    print(f"  실패한 번호: {failed or '없음'}" + ("  → 다시 실행하면 이 번호만 받는다" if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
