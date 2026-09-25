"""수강편람 갱신 스크립트 (SNUTT의 sugangSnuMigrationJob에 해당).

갱신 정책
- 기본: 12시간마다
- 부스트 1: 새 학기 편람을 감지한 시각부터 30일간 6시간마다
- 부스트 2: 수강신청 기간(장바구니 시작 3일 전 ~ 수강신청변경 마감 3일 후) 6시간마다
  일정은 첫 화면 일정표를 파싱해 읽는다. 표가 없으면(방학 등) 기본 주기로.

실행할 때마다 하는 일
1. 현재 학기 확인 → 바뀌었으면 detected_at 갱신
2. 정책상 아직 때가 아니면 종료 (GitHub Actions cron은 6시간마다 이 스크립트를 부르고, 실제 다운로드
   여부는 여기서 결정한다)
3. 엑셀 다운로드 → 파싱 → 이전 lectures.json과 (교과목번호, 강좌번호) 키로 비교
4. 바뀐 게 있으면 lectures.json 갱신 + changes/ 에 diff 기록 + raw/ 에 날짜별 원본 보관
5. stats.csv 에 (시각, 분반 수, 강의실 확정 수) 한 줄 추가 — 보고서 그래프용

사용법
  python scripts/sync.py            # 정책대로
  python scripts/sync.py --force    # 무조건 다운로드
  python scripts/sync.py --dry-run  # 다운로드만 하고 파일은 안 건드림
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ttwizard.parse_sugang import location_stats, parse_sugang_excel, sections_from_json, sections_to_json  # noqa: E402
import sugang_client as sc  # noqa: E402

DATA = ROOT / "data"
STATE = DATA / "sync_state.json"
LECTURES = DATA / "lectures.json"
CHANGES = DATA / "changes"
RAW = DATA / "raw"
STATS = DATA / "stats.csv"

KST = timezone(timedelta(hours=9))
BASE_INTERVAL = timedelta(hours=12)
BOOST_INTERVAL = timedelta(hours=6)
NEW_SEMESTER_BOOST_DAYS = 30
REG_MARGIN_DAYS = 3
BOOST_TYPES = ("장바구니", "선착순", "수강신청변경")  # 부스트 2에 포함할 일정표 '구분' 키워드


def now_kst() -> datetime:
    return datetime.now(KST)


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def parse_iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def boost_window(windows: list[dict]) -> tuple[date, date] | None:
    """일정표에서 부스트 2 구간 계산. 해당 유형이 없으면 None."""
    rel = [w for w in windows if any(k in w["type"] for k in BOOST_TYPES)]
    if not rel:
        return None
    start = min(w["start"] for w in rel) - timedelta(days=REG_MARGIN_DAYS)
    end = max(w["end"] for w in rel) + timedelta(days=REG_MARGIN_DAYS)
    return start, end


def decide_interval(now: datetime, state: dict, windows: list[dict]) -> tuple[timedelta, str]:
    detected = parse_iso(state.get("detected_at"))
    if detected and now - detected < timedelta(days=NEW_SEMESTER_BOOST_DAYS):
        return BOOST_INTERVAL, f"새 학기 감지 후 {(now - detected).days}일째"
    bw = boost_window(windows)
    if bw and bw[0] <= now.date() <= bw[1]:
        return BOOST_INTERVAL, f"수강신청 기간 {bw[0]}~{bw[1]}"
    return BASE_INTERVAL, "기본"


def diff_sections(old: list, new: list) -> dict:
    """(교과목번호, 강좌번호) 키로 신설/변경/삭제를 찾는다. 변경은 어떤 필드가 바뀌었는지 기록."""
    def as_dict(s):
        return {
            "course_name": s.course_name, "instructor": s.instructor, "department": s.department,
            "credit": s.credit, "classification": s.classification,
            "meetings": [(m.day, m.start, m.end, m.building, m.room) for m in s.meetings],
        }

    om = {s.key: s for s in old}
    nm = {s.key: s for s in new}
    created = sorted(nm.keys() - om.keys())
    deleted = sorted(om.keys() - nm.keys())
    updated = []
    for k in sorted(nm.keys() & om.keys()):
        a, b = as_dict(om[k]), as_dict(nm[k])
        fields = [f for f in a if a[f] != b[f]]
        if fields:
            updated.append({"key": k, "fields": fields, "before": {f: a[f] for f in fields}, "after": {f: b[f] for f in fields}})
    return {"created": created, "deleted": deleted, "updated": updated}


def append_stats(ts: datetime, label: str, stats: dict) -> None:
    new_file = not STATS.exists()
    with open(STATS, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp", "semester", "sections_total", "sections_timed", "sections_located",
                        "located_ratio", "courses", "courses_multi_section", "courses_multi_building",
                        "multi_building_ratio", "buildings"])
        w.writerow([ts.isoformat(timespec="minutes"), label] + [stats[k] for k in (
            "sections_total", "sections_timed", "sections_located", "located_ratio", "courses",
            "courses_multi_section", "courses_multi_building", "multi_building_ratio", "buildings")])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    CHANGES.mkdir(exist_ok=True)
    RAW.mkdir(exist_ok=True)
    now = now_kst()
    state = load_state()

    s = sc.new_session()
    cb = sc.current_coursebook(s)
    if state.get("semester") != cb.label:
        print(f"새 학기 편람 감지: {state.get('semester')} → {cb.label}")
        state["semester"] = cb.label
        state["detected_at"] = now.isoformat(timespec="minutes")

    try:
        windows = sc.registration_windows(s)
    except Exception as e:  # 일정표 파싱 실패는 치명적이지 않다
        print(f"일정표 파싱 실패, 기본 주기 사용: {e}")
        windows = []
    state["registration_windows"] = [
        {"type": w["type"], "start": w["start"].isoformat(), "end": w["end"].isoformat()} for w in windows
    ]

    interval, reason = decide_interval(now, state, windows)
    last = parse_iso(state.get("last_fetch"))
    due = last is None or now - last >= interval - timedelta(minutes=30)
    print(f"학기 {cb.label} · 주기 {interval} ({reason}) · 마지막 {last} · {'실행' if (due or args.force) else '건너뜀'}")
    if not (due or args.force):
        if not args.dry_run:
            save_state(state)
        return 0

    data = sc.download_excel(s, cb, "ko")
    ext = sc.excel_extension(data)
    latest = RAW / f"latest{ext}"
    latest.write_bytes(data)
    new_sections = parse_sugang_excel(latest)
    old_sections = sections_from_json(LECTURES) if LECTURES.exists() else []
    d = diff_sections(old_sections, new_sections)
    stats = location_stats(new_sections)
    print(f"분반 {stats['sections_total']}개 (학사·설강·시간 있음 {stats['sections_timed']}개, 강의실 확정 {stats['located_ratio']:.1%}) · "
          f"신설 {len(d['created'])} · 변경 {len(d['updated'])} · 삭제 {len(d['deleted'])}")

    if args.dry_run:
        return 0

    stamp = now.strftime("%Y-%m-%d_%H%M")
    changed = any(d[k] for k in ("created", "updated", "deleted")) or not LECTURES.exists()
    if changed:
        sections_to_json(new_sections, LECTURES)
        (CHANGES / f"{stamp}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        (RAW / f"{cb.label}_{stamp}{ext}").write_bytes(data)  # 바뀐 때만 원본 보관 (용량 관리)
    append_stats(now, cb.label, stats)
    state["last_fetch"] = now.isoformat(timespec="minutes")
    state["last_change"] = stamp if changed else state.get("last_change")
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
