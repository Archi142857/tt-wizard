"""엑셀 파싱과 갱신 정책 테스트 (네트워크 없이)."""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ttwizard.parse_sugang import location_stats, parse_sugang_excel  # noqa: E402
import sync  # noqa: E402

KST = timezone(timedelta(hours=9))


def _fake_excel(path: Path) -> None:
    """수강편람 엑셀 모양: 제목 줄 2개 + 헤더 + 데이터."""
    header = ["교과구분", "개설대학", "개설학과", "이수과정", "학년", "교과목번호", "강좌번호", "교과목명", "부제명",
              "학점", "강의", "실습", "수업교시", "수업형태", "강의실(동-호)(#연건, *평창)", "주담당교수", "정원", "수강신청인원", "비고"]
    rows = [
        ["전선", "농업생명과학대학", "식품·동물생명공학부", "학사", "3", "M1101.000100", 1, "동물생리학", "", 3, 3, 0,
         "월(09:30~10:45)/수(09:30~10:45)", "이론", "200-205/200-205", "김OO", 40, 38, ""],
        ["전선", "농업생명과학대학", "식품·동물생명공학부", "학사", "3", "M1101.000100", 2, "동물생리학", "", 3, 3, 0,
         "화(11:00~12:15)/목(11:00~12:15)", "이론", "220-1-201", "이OO", 40, 12, ""],
        ["교양", "기초교육원", "기초교육원", "학사", "1", "L0444.000100", 12, "대학글쓰기", "인문학 글쓰기", 3, 3, 0,
         "금(09:00~11:50)", "이론", "083-101", "한OO", 20, 20, ""],
        ["전필", "의과대학", "의학과", "학사", "2", "M9999.000100", 1, "해부학", "", 3, 3, 0,
         "월(09:00~09:50)", "이론", "#101-1-2", "박OO", 100, 100, ""],
        ["전선", "공과대학", "화학생물공학부", "학사", "3", "M1103.000100", 1, "화공열역학", "", 3, 3, 0,
         "월(14:00~15:15)/수(14:00~15:15)", "이론", "미정", "정OO", 60, 0, ""],
    ]
    df = pd.DataFrame([["2026학년도 2학기 개설강좌"] + [""] * (len(header) - 1), [""] * len(header), header] + rows)
    df.to_excel(path, header=False, index=False)


def test_parse_excel_layout(tmp_path):
    p = tmp_path / "coursebook.xlsx"
    _fake_excel(p)
    secs = parse_sugang_excel(p)  # 관악만
    keys = {s.key for s in secs}
    assert "M1101.000100-001" in keys and "M1101.000100-012" not in keys
    assert "L0444.000100-012" in keys  # 강좌번호 12 → '012'
    assert "M9999.000100-001" not in keys  # 연건 제외
    a = next(s for s in secs if s.key == "M1101.000100-002")
    assert [m.building for m in a.meetings] == ["220-1", "220-1"]
    g = next(s for s in secs if s.key == "L0444.000100-012")
    assert g.course_name == "대학글쓰기 (인문학 글쓰기)" and g.meetings[0].building == "83"
    c = next(s for s in secs if s.key == "M1103.000100-001")
    assert not c.has_location  # 미정
    st = location_stats(secs)
    assert st["sections"] == 4 and st["sections_with_location"] == 3

    all_secs = parse_sugang_excel(p, campus=None)
    assert len(all_secs) == 5


def test_decide_interval():
    now = datetime(2026, 7, 10, 12, 0, tzinfo=KST)
    # 새 학기 감지 후 7일 → 6시간
    st = {"detected_at": (now - timedelta(days=7)).isoformat()}
    assert sync.decide_interval(now, st, []) == (sync.BOOST_INTERVAL, "새 학기 감지 후 7일째")
    # 감지 후 40일, 일정표 없음 → 12시간
    st = {"detected_at": (now - timedelta(days=40)).isoformat()}
    assert sync.decide_interval(now, st, [])[0] == sync.BASE_INTERVAL
    # 감지 후 40일이지만 수강신청 기간 → 6시간 (장바구니 8/10~8/12, 변경 9/1~9/7, 여유 3일)
    windows = [
        {"type": "장바구니 신청", "start": date(2026, 8, 10), "end": date(2026, 8, 12)},
        {"type": "수강신청변경", "start": date(2026, 9, 1), "end": date(2026, 9, 7)},
        {"type": "예비수강신청", "start": date(2026, 7, 20), "end": date(2026, 7, 22)},  # 부스트 대상 아님
    ]
    assert sync.boost_window(windows) == (date(2026, 8, 7), date(2026, 9, 10))
    t = datetime(2026, 8, 8, 9, 0, tzinfo=KST)
    assert sync.decide_interval(t, st, windows)[0] == sync.BOOST_INTERVAL
    t = datetime(2026, 7, 21, 9, 0, tzinfo=KST)  # 예비수강신청만 있는 날 → 기본
    assert sync.decide_interval(t, st, windows)[0] == sync.BASE_INTERVAL


def test_diff_sections(tmp_path):
    p = tmp_path / "a.xlsx"
    _fake_excel(p)
    old = parse_sugang_excel(p, campus=None)
    new = list(old)
    # 강의실이 채워진 경우를 흉내: 화공열역학 미정 → 302-106
    from dataclasses import replace

    from ttwizard.models import Meeting
    c = next(s for s in new if s.key == "M1103.000100-001")
    new.remove(c)
    new.append(replace(c, meetings=tuple(Meeting(m.day, m.start, m.end, "302", "302-106") for m in c.meetings)))
    new = [s for s in new if s.key != "M9999.000100-001"]  # 폐강
    d = sync.diff_sections(old, new)
    assert d["deleted"] == ["M9999.000100-001"]
    assert d["created"] == []
    assert len(d["updated"]) == 1 and d["updated"][0]["fields"] == ["meetings"]
