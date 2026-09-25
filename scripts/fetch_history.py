"""과거 학기 수강편람을 학기별로 한 번씩 받아, 강의가 한 번이라도 열렸던 건물 목록을 만든다.

  python scripts/fetch_history.py                  # 2021-1 ~ 현재 학기 (봄·여름·가을·겨울)
  python scripts/fetch_history.py --from 2019      # 시작 연도 변경
  python scripts/fetch_history.py --no-seasonal    # 1·2학기만

- 엑셀은 data/raw/history/<년도>-<학기>.xls 에 저장하고, 이미 있으면 다시 받지 않는다 (재실행 안전)
- 요청은 학기당 1회, 사이에 --sleep 초(기본 4초) 쉰다. 5년치 23학기면 2분 정도
- 결과: data/buildings_history.csv — building, first_seen, last_seen, semesters, sections
  (관악 강좌만, 이수과정 무관. 위치가 적힌 강좌 기준)
- 이어서 python scripts/fetch_buildings.py --history 로 좌표를 받는다

주의: 옛 학기 엑셀은 열 이름이 조금 다를 수 있다. 파서가 헤더를 못 찾으면 그 학기는 건너뛰고 로그에 남긴다.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ttwizard.parse_sugang import parse_sugang_excel  # noqa: E402
import sugang_client as sc  # noqa: E402

HISTORY = ROOT / "data" / "raw" / "history"
OUT = ROOT / "data" / "buildings_history.csv"
SEMESTER_ORDER = ["1", "S", "2", "W"]


def semester_list(start_year: int, current: sc.Coursebook, seasonal: bool) -> list[sc.Coursebook]:
    out = []
    for year in range(start_year, current.year + 1):
        for sem in SEMESTER_ORDER:
            if not seasonal and sem in ("S", "W"):
                continue
            cb = sc.Coursebook(year=year, code=sc.CODE_OF_SEMESTER[sem])
            # 현재 학기 이후는 없음
            if year == current.year and SEMESTER_ORDER.index(sem) > SEMESTER_ORDER.index(current.semester):
                continue
            out.append(cb)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=2021)
    ap.add_argument("--no-seasonal", action="store_true")
    ap.add_argument("--sleep", type=float, default=4.0)
    args = ap.parse_args()

    HISTORY.mkdir(parents=True, exist_ok=True)
    s = sc.new_session()
    current = sc.current_coursebook(s)
    targets = semester_list(args.start, current, seasonal=not args.no_seasonal)
    print(f"현재 학기 {current.label}, 대상 {len(targets)}개 학기")

    stats: dict[str, dict] = defaultdict(lambda: {"first": None, "last": None, "semesters": 0, "sections": 0})
    failed: list[str] = []
    for cb in targets:
        existing = list(HISTORY.glob(f"{cb.label}.xls*"))
        if existing:
            path = existing[0]
            print(f"  {cb.label}: 저장본 사용 ({path.name})")
        else:
            try:
                data = sc.download_excel(s, cb, "ko")
            except Exception as e:
                print(f"  {cb.label}: 다운로드 실패 — {e}")
                failed.append(cb.label)
                time.sleep(args.sleep)
                continue
            path = HISTORY / f"{cb.label}{sc.excel_extension(data)}"
            path.write_bytes(data)
            print(f"  {cb.label}: {len(data) // 1024} KB 저장")
            time.sleep(args.sleep)
        try:
            sections = parse_sugang_excel(path)  # 관악만
        except Exception as e:
            print(f"  {cb.label}: 파싱 실패 — {e}")
            failed.append(cb.label)
            continue
        seen_this = set()
        for sec in sections:
            for b in sec.buildings:
                st = stats[b]
                st["sections"] += 1
                if b not in seen_this:
                    seen_this.add(b)
                    st["semesters"] += 1
                    st["first"] = st["first"] or cb.label
                    st["last"] = cb.label
        print(f"      분반 {len(sections)}개, 건물 {len(seen_this)}개, 누적 건물 {len(stats)}개")

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["building", "first_seen", "last_seen", "semesters", "sections"])
        for b in sorted(stats, key=lambda x: (not x.split("-")[0].isdigit(), len(x.split("-")[0]), x)):
            st = stats[b]
            w.writerow([b, st["first"], st["last"], st["semesters"], st["sections"]])
    print(f"\n저장: {OUT} (건물 {len(stats)}개). 실패한 학기: {failed or '없음'}")
    print("다음: python scripts/fetch_buildings.py --history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
