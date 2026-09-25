"""신용범 님(캠퍼스 마법 지도)께 보낼 건물 목록 CSV를 만든다.

  python scripts/export_magicmap.py
→ data/buildings_for_magicmap.csv : building, name, lat, lon, first_seen, last_seen, note

data/buildings.csv(좌표) + data/buildings_history.csv(있으면, 언제부터 강의가 열렸는지) 를 합치고,
출발/도착 후보(정문 GATE, 기숙사 919)가 없으면 근사값으로 넣어 note 에 표시한다.
엑셀에서 한글이 안 깨지도록 UTF-8 BOM 으로 저장.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILDINGS = ROOT / "data" / "buildings.csv"
HISTORY = ROOT / "data" / "buildings_history.csv"
OUT = ROOT / "data" / "buildings_for_magicmap.csv"

EXTRA = {
    "919": {"name": "관악학생생활관 919동 (출발/도착 후보)", "lat": "37.45280", "lon": "126.95750", "note": "근사값 — 확인 필요"},
    "GATE": {"name": "정문 (출발/도착 후보)", "lat": "37.46620", "lon": "126.94900", "note": "근사값"},
}


def main() -> int:
    rows = {}
    with open(BUILDINGS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[r["building"]] = {**r, "note": "서울대 캠퍼스맵 API"}
    hist = {}
    if HISTORY.exists():
        with open(HISTORY, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                hist[r["building"]] = r
                if r["building"] not in rows:
                    rows[r["building"]] = {"building": r["building"], "name": "", "lat": "", "lon": "",
                                           "note": "캠퍼스맵 미검색 — 좌표 필요"}
    for b, extra in EXTRA.items():
        if b not in rows:
            rows[b] = {"building": b, **extra}
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["building", "name", "lat", "lon", "first_seen", "last_seen", "note"])
        w.writeheader()
        for b in sorted(rows, key=lambda x: (not x.split("-")[0].isdigit(), len(x.split("-")[0]), x)):
            r = rows[b]
            h = hist.get(b, {})
            w.writerow({"building": b, "name": r.get("name", ""), "lat": r.get("lat", ""), "lon": r.get("lon", ""),
                        "first_seen": h.get("first_seen", ""), "last_seen": h.get("last_seen", ""), "note": r.get("note", "")})
    print(f"저장: {OUT} ({len(rows)}개, 좌표 없음 {sum(1 for r in rows.values() if not r.get('lat'))}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
