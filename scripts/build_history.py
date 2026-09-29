"""지난 학기 편람 엑셀(data/raw/history/<학기>.xls) → data/history/<학기>.json (웹 화면 courses.json 형식).

  python scripts/build_history.py          # 아직 없는 학기만
  python scripts/build_history.py --all    # 전부 다시

웹 화면의 학기 선택이 읽는다. Pages 배포(export_web.py)는 pip 설치 없이 돌아야 해서 엑셀 대신 이 파일을 쓴다.
지금 학기는 data/lectures.json 을 쓰므로 만들지 않는다. 학기가 바뀌면 sync.py 가 끝난 학기를 여기에 보관한다
(그때는 마지막 lectures.json 으로 덮어쓴다). 지난 학기 엑셀은 scripts/fetch_history.py 가 받는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import export_web  # noqa: E402
from ttwizard.parse_sugang import parse_sugang_excel, sections_to_rows  # noqa: E402

DATA = ROOT / "data"
RAW = DATA / "raw" / "history"
OUT = DATA / "history"


def write_semester(label: str, rows: list[dict], out: Path = OUT, updated: str = "") -> Path:
    """분반 목록(lectures.json 형식) → out/<학기>.json (웹 형식, 한 줄)."""
    payload = export_web.courses_from_rows(rows)
    payload["meta"] = {"semester": label, "updated": updated}
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{label}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="이미 있는 학기도 다시 만든다")
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("-o", "--output", default=str(OUT))
    args = ap.parse_args(argv)
    current = export_web.current_semester(DATA)
    out = Path(args.output)
    for xls in sorted(Path(args.raw).glob("*.xls*"), key=lambda p: export_web.semester_key(p.stem)):
        label = xls.stem
        if export_web.semester_key(label) == (-1, -1):
            continue
        if label == current:
            print(f"  {label}: 지금 학기라 건너뜀 (data/lectures.json 을 쓴다)")
            continue
        if (out / f"{label}.json").exists() and not args.all:
            continue
        path = write_semester(label, sections_to_rows(parse_sugang_excel(xls)), out)
        print(f"  {label}: {path.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
