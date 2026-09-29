"""캠퍼스 마법 지도 건물쌍 거리표 → data/travel.csv (시간표 알고리즘 입력).

  python scripts/magicmap_travel.py

입력  data/magicmap/building_pair_times.csv   from,to,distance_m,time_s (109개 지점의 모든 방향 쌍, time = 거리 ÷ 1.1 m/s)
출력  data/travel.csv                          from,to,minutes,source (ttwizard/travel.py 형식, source = magicmap)
      이미 있는 travel.csv 는 합친다: 표에 있는 쌍은 마법 지도 값으로 바꾸되 measured(실측) 행은 그대로 두고,
      표에 없는 쌍(TMAP 등)은 남긴다
출처  캠퍼스 마법 지도 (https://moreadorecampus.com/)
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAIRS = ROOT / "data" / "magicmap" / "building_pair_times.csv"
TRAVEL = ROOT / "data" / "travel.csv"


def read_pairs(path: Path) -> dict[tuple[str, str], float]:
    """(from, to) → 분."""
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            a, b = r["from"].strip(), r["to"].strip()
            if a and b and a != b:
                out[(a, b)] = float(r["time_s"]) / 60
    return out


def read_existing(path: Path) -> dict[tuple[str, str], tuple[float, str]]:
    rows = {}
    if not path.exists():
        return rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows[(r["from"].strip(), r["to"].strip())] = (float(r["minutes"]), (r.get("source") or "").strip())
    return rows


def build(pairs: dict[tuple[str, str], float], existing: dict[tuple[str, str], tuple[float, str]]):
    rows = dict(existing)
    for k, m in pairs.items():
        if existing.get(k, (0.0, ""))[1] != "measured":
            rows[k] = (m, "magicmap")
    return rows


def write(rows: dict[tuple[str, str], tuple[float, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:  # travel.py 가 BOM 없는 UTF-8로 읽는다
        w = csv.writer(f)
        w.writerow(["from", "to", "minutes", "source"])
        for (a, b), (m, src) in sorted(rows.items()):
            w.writerow([a, b, f"{m:.2f}", src])


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=str(PAIRS))
    ap.add_argument("-o", "--output", default=str(TRAVEL))
    args = ap.parse_args(argv)
    pairs = read_pairs(Path(args.pairs))
    existing = read_existing(Path(args.output))
    rows = build(pairs, existing)
    write(rows, Path(args.output))
    ids = {a for a, _ in pairs} | {b for _, b in pairs}
    mins = sorted(m for m, _ in rows.values())
    kept = sum(1 for k, (_, src) in rows.items() if src != "magicmap")
    print(f"저장: {args.output} ({len(rows):,}쌍, 마법 지도 지점 {len(ids)}개, 그 밖에 남긴 행(실측·TMAP 등) {kept}쌍)")
    if mins:
        print(f"  이동시간: 최소 {mins[0]:.1f}분, 중앙값 {mins[len(mins) // 2]:.1f}분, 최대 {mins[-1]:.1f}분 (거리 ÷ 1.1 m/s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
