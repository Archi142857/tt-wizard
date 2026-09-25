"""명령줄 인터페이스.

  python -m ttwizard demo                              # 샘플 데이터로 바로 실행
  python -m ttwizard parse data/raw/2026-2.xls -o data/lectures.json
  python -m ttwizard find  --lectures data/lectures.json 생화학
  python -m ttwizard search --lectures data/lectures.json \
        --courses M1234.000100,M2345.000200 --home 919 --top 5 --json data/results.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bound import tsp_lower_bound
from .evaluate import Weights
from .models import Course, group_into_courses, min_to_hm
from .parse_sugang import location_stats, parse_sugang_excel, sections_from_json, sections_to_json
from .search import search
from .travel import TravelMatrix

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"


def _load_travel(args) -> TravelMatrix:
    return TravelMatrix.load(args.buildings, args.travel)


def _print_result(result, travel: TravelMatrix, home: str, top: int) -> None:
    st = result.stats
    print(
        f"과목 {st.n_courses}개, 이론상 조합 {st.n_combinations:,}개, 평가 {st.leaves:,}개, "
        f"충돌 가지치기 {st.pruned_conflict:,}, 하한 가지치기 {st.pruned_bound:,}, {st.seconds:.2f}초"
    )
    if result.lower_bound is not None:
        print(f"TSP 하한 {result.lower_bound:.0f}분/주 (내부 지표)")
    for i, ev in enumerate(result.ranked[:top], start=1):
        print(f"\n[{i}위] {ev.summary()}")
        for s in ev.sections:
            times = ", ".join(str(m) for m in s.meetings)
            print(f"  - {s.course_name} ({s.section_no}분반, {s.instructor or '교수 미정'}): {times}")
        for d, meetings in ev.days.items():
            legs = [lg for lg in ev.legs if lg.day == d]
            route = " → ".join([home] + [lg.to for lg in legs])
            mins = " / ".join(f"{lg.minutes:.0f}분" + (f"(여유 {lg.slack:.0f})" if lg.slack is not None else "") for lg in legs)
            print(f"    {meetings[0].day_ko}: {route}   [{mins}]")


def cmd_demo(args) -> int:
    args.buildings = SAMPLE / "buildings.csv"
    args.travel = SAMPLE / "travel.csv"
    sections = sections_from_json(SAMPLE / "lectures.json")
    courses = list(group_into_courses(sections).values())
    travel = _load_travel(args)
    home = args.home or "919"
    result = search(courses, travel, home, top_k=args.top, weights=Weights())
    result.lower_bound = tsp_lower_bound(courses, travel, home)
    print("샘플 데이터 (가짜 강좌·근사 좌표) — 실제 수강편람으로 바꾸면 결과가 달라집니다.\n")
    _print_result(result, travel, home, args.top)
    if args.json:
        from .export import export_results

        export_results(result, travel, home, args.json)
        print(f"\nJSON 저장: {args.json}")
    return 0


def cmd_parse(args) -> int:
    sections = parse_sugang_excel(args.excel, campus=None if args.all_campus else "관악")
    stats = location_stats(sections)
    print(f"분반 {stats['sections']}개, 강의실 확정 {stats['sections_with_location']}개 ({stats['location_ratio']:.1%})")
    print(f"과목 {stats['courses']}개, 분반이 서로 다른 동에서 열리는 과목 {stats['courses_with_multiple_buildings']}개 ({stats['multi_building_ratio']:.1%})")
    if args.output:
        sections_to_json(sections, args.output)
        print(f"저장: {args.output}")
    return 0


def cmd_find(args) -> int:
    sections = sections_from_json(args.lectures)
    q = args.query.lower()
    courses = group_into_courses(s for s in sections if q in s.course_name.lower() or q in s.course_id.lower() or q in s.instructor.lower())
    for c in courses.values():
        print(f"{c.course_id}  {c.name}  [{c.n_sections}분반]  {c.sections[0].department}")
        for s in c.sections:
            print(f"    {s.section_no}  {s.instructor or '-':10s}  " + ", ".join(str(m) for m in s.meetings))
    if not courses:
        print("검색 결과 없음")
    return 0


def cmd_search(args) -> int:
    sections = sections_from_json(args.lectures)
    wanted = [c.strip() for c in args.courses.split(",") if c.strip()]
    excluded = set(x.strip() for x in (args.exclude or "").split(",") if x.strip())
    by_course = group_into_courses(s for s in sections if s.course_id in wanted and s.key not in excluded)
    missing = [c for c in wanted if c not in by_course]
    if missing:
        print(f"경고: 찾지 못한 교과목번호 {missing}", file=sys.stderr)
    courses: list[Course] = [by_course[c] for c in wanted if c in by_course]
    if args.require_location:
        for c in courses:
            c.sections = [s for s in c.sections if s.has_location]
    travel = _load_travel(args)
    w = Weights(late=args.late_weight, campus_day=args.day_weight)
    result = search(courses, travel, args.home, top_k=args.top, weights=w)
    result.lower_bound = tsp_lower_bound(courses, travel, args.home)
    _print_result(result, travel, args.home, args.top)
    if args.json:
        from .export import export_results

        export_results(result, travel, args.home, args.json)
        print(f"\nJSON 저장: {args.json}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ttwizard", description="동선 고려 시간표 생성기")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="샘플 데이터로 실행")
    d.add_argument("--top", type=int, default=5)
    d.add_argument("--home", default=None)
    d.add_argument("--json", default=None)
    d.set_defaults(fn=cmd_demo)

    pp = sub.add_parser("parse", help="수강편람 엑셀 → lectures.json")
    pp.add_argument("excel")
    pp.add_argument("-o", "--output", default=None)
    pp.add_argument("--all-campus", action="store_true", help="연건·평창 포함")
    pp.set_defaults(fn=cmd_parse)

    f = sub.add_parser("find", help="과목명/교과목번호/교수로 검색")
    f.add_argument("query")
    f.add_argument("--lectures", default="data/lectures.json")
    f.set_defaults(fn=cmd_find)

    s = sub.add_parser("search", help="분반 조합 탐색")
    s.add_argument("--lectures", default="data/lectures.json")
    s.add_argument("--courses", required=True, help="교과목번호를 쉼표로")
    s.add_argument("--exclude", default="", help="뺄 분반 키 (교과목번호-강좌번호)를 쉼표로")
    s.add_argument("--home", default="919", help="출발/도착 건물 id (기숙사 919, 정문 GATE 등)")
    s.add_argument("--buildings", default="data/buildings.csv")
    s.add_argument("--travel", default="data/travel.csv")
    s.add_argument("--top", type=int, default=5)
    s.add_argument("--late-weight", type=float, default=2.0)
    s.add_argument("--day-weight", type=float, default=0.0)
    s.add_argument("--require-location", action="store_true", help="강의실 미정 분반 제외")
    s.add_argument("--json", default=None)
    s.set_defaults(fn=cmd_search)

    args = p.parse_args(argv)
    return args.fn(args)
