"""pytest tests — `python -m pytest -q` 로 실행."""

from pathlib import Path

import pytest

from ttwizard.bound import tsp_lower_bound
from ttwizard.evaluate import Weights, evaluate
from ttwizard.models import Meeting, Section, group_into_courses
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
