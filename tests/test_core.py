"""pytest tests — `python -m pytest -q` 로 실행."""

from pathlib import Path

import pytest

from ttwizard.bound import tsp_lower_bound
from ttwizard.evaluate import Weights, evaluate
from ttwizard.models import Course, Meeting, Section, group_into_courses
from ttwizard.parse_sugang import parse_building, parse_meetings, sections_from_json
from ttwizard.search import brute_force, search
from ttwizard.travel import TravelMatrix

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def test_overlap_rules():
    a = Meeting(0, 570, 645, "200")
    b = Meeting(0, 645, 735, "504")  # 끝==시작 → 겹침 아님
    c = Meeting(0, 600, 660, "504")
    d = Meeting(1, 600, 660, "504")  # 다른 요일
    assert not a.overlaps(b)
    assert a.overlaps(c)
    assert not a.overlaps(d)


@pytest.mark.parametrize(
    "place,expected",
    [
        ("301-118", ("301", "관악")),
        ("220-1-201", ("220-1", "관악")),
        ("083-302", ("83", "관악")),
        ("#101-1-2", ("101-1", "연건")),
        ("*201", ("201", "평창")),
        ("미정", ("", "관악")),
        ("", ("", "관악")),
        ("301-118(무선랜제공)", ("301", "관악")),
    ],
)
def test_parse_building(place, expected):
    assert parse_building(place) == expected


def test_parse_meetings_pairs_rooms():
    ms, campuses = parse_meetings("월(09:30~10:45)/수(09:30~10:45)", "301-118/302-106")
    assert [m.building for m in ms] == ["301", "302"]
    assert ms[0].day == 0 and ms[0].start == 570 and ms[0].end == 645
    assert campuses == {"관악"}

    ms, _ = parse_meetings("화(14:00~15:15)/목(14:00~15:15)", "504-105")
    assert [m.building for m in ms] == ["504", "504"]

    ms, _ = parse_meetings("", "")
    assert ms == []


def _sample():
    sections = sections_from_json(SAMPLE / "lectures.json")
    courses = list(group_into_courses(sections).values())
    travel = TravelMatrix.load(SAMPLE / "buildings.csv", SAMPLE / "travel.csv")
    return courses, travel


def test_search_matches_brute_force():
    courses, travel = _sample()
    for weights in (Weights(), Weights(late=50.0, campus_day=10.0)):
        bf = brute_force(courses, travel, "919", weights)
        res = search(courses, travel, "919", top_k=5, weights=weights)
        assert [round(e.cost, 6) for e in res.ranked] == [round(e.cost, 6) for e in bf[:5]]
        assert res.stats.leaves <= res.stats.n_combinations


def test_conflicting_sections_never_selected():
    courses, travel = _sample()
    res = search(courses, travel, "919", top_k=20)
    for ev in res.ranked:
        secs = ev.sections
        for i in range(len(secs)):
            for j in range(i + 1, len(secs)):
                assert not secs[i].conflicts_with(secs[j])


def test_lower_bound_is_lower():
    courses, travel = _sample()
    res = search(courses, travel, "919", top_k=1)
    lb = tsp_lower_bound(courses, travel, "919")
    assert lb <= res.ranked[0].travel_minutes + 1e-9


def test_late_penalty():
    travel = TravelMatrix.load(SAMPLE / "buildings.csv", SAMPLE / "travel.csv")
    # 200동 10:45 끝 → 302동 11:00 시작, 이동 18분 → 3분 지각
    a = Section("X", "001", "A", (Meeting(0, 570, 645, "200"),))
    b = Section("Y", "001", "B", (Meeting(0, 660, 735, "302"),))
    ev = evaluate([a, b], travel, "919", Weights(late=2.0))
    assert ev.late_minutes == pytest.approx(3.0)
    assert ev.cost == pytest.approx(ev.travel_minutes + 6.0)


def test_duplicate_meetings_are_merged():
    """같은 시간·같은 건물의 두 강의실(반을 나눈 경우)은 한 번의 수업으로 본다."""
    ms, _ = parse_meetings("월(12:30~13:45)/수(17:00~17:50)/수(17:00~17:50)", "8-304/5-116/5-208")
    assert len(ms) == 2
    wed = [m for m in ms if m.day == 2][0]
    assert wed.building == "5" and wed.room == "5-116/5-208"


def _shortcut_case():
    """a→b(15분)가 a→c→b(2분)보다 훨씬 긴 행렬. 출입구가 여러 곳인 건물 c를 지나가는 지름길과 같은 모양."""
    t = {("h", "a"): 1, ("h", "b"): 1, ("h", "c"): 1, ("a", "b"): 15, ("a", "c"): 1, ("c", "b"): 1,
         ("h", "x"): 20, ("h", "y"): 5, ("h", "z"): 5}
    travel = TravelMatrix(table={**t, **{(b, a): v for (a, b), v in t.items()}}, default_minutes=30.0)

    def sec(course, no, day, start, building):
        return Section(course, no, course, (Meeting(day, start, start + 60, building),))

    courses = [
        Course("A", "A", [sec("A", "1", 0, 540, "a"), sec("A", "2", 1, 540, "x")]),
        Course("B", "B", [sec("B", "1", 2, 540, "y"), sec("B", "2", 0, 780, "b")]),
        Course("C", "C", [sec("C", "1", 0, 660, "c"), sec("C", "2", 3, 540, "z"), sec("C", "3", 4, 540, "z")]),
    ]
    return courses, travel


def test_closure():
    _, travel = _shortcut_case()
    c = travel.closure(["h", "a", "b", "c"])
    assert c.minutes("a", "b") == 2 and c.minutes("a", "c") == 1 and travel.minutes("a", "b") == 15
    assert not travel.misses and not c.misses


def test_bound_survives_triangle_violation():
    # 원래 행렬로 부분 비용을 재면 (A1, B2) 가지(월 집→a→b→집 = 17분)를 13분짜리 해 때문에 버려
    # 최적해 A1·B2·C1(월 집→a→c→b→집 = 4분)을 놓친다
    courses, travel = _shortcut_case()
    bf = brute_force(courses, travel, "h")
    res = search(courses, travel, "h", top_k=1)
    assert bf[0].cost == pytest.approx(4.0)
    assert res.ranked[0].cost == pytest.approx(4.0)
    assert tsp_lower_bound(courses, travel, "h") <= res.ranked[0].travel_minutes + 1e-9


def test_unknown_room_adds_no_travel_or_lateness():
    t = {("h", "a"): 16, ("h", "b"): 5, ("a", "b"): 20}
    travel = TravelMatrix(table={**t, **{(b, a): v for (a, b), v in t.items()}}, default_minutes=30.0)

    def sec(name, start, end, building):
        return Section(name, "001", name, (Meeting(2, start, end, building),))

    # 그날 첫 수업이 강의실 미정(12:30~13:45)이고 15분 뒤 a(16분 거리): 집(정문)에서 출발한다고 보지 않으므로 지각 없음
    ev = evaluate([sec("U", 750, 825, ""), sec("A", 840, 950, "a")], travel, "h")
    assert ev.late_minutes == 0 and ev.travel_minutes == 32  # 집 → a → 집
    # 위치 확정 수업 사이의 미정 수업: 앞뒤 쉬는 시간(10분 + 10분)을 b → a(20분) 이동에 함께 쓴다
    b, u = sec("B", 540, 600, "b"), sec("U", 610, 700, "")
    assert evaluate([b, u, sec("A", 710, 800, "a")], travel, "h").late_minutes == 0
    assert evaluate([b, u, sec("A", 705, 800, "a")], travel, "h").late_minutes == pytest.approx(5)  # 10 + 5 < 20


def test_section_label():
    """분반 표기는 061(나민애). 교수가 없으면 061(교수 미정)."""
    assert Section("X", "061", "과목", (), instructor="나민애").label == "061(나민애)"
    assert Section("X", "002", "과목", ()).label == "002(교수 미정)"
    assert Section("X", "003", "과목", (), instructor="  ").label == "003(교수 미정)"
