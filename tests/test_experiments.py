"""비교 실험 스크립트(scripts/experiments.py): 조합 세기, 무작위 표본, 요약, 후보 분반 (수강 제한 규칙은 test_restrictions.py)."""

import random
import sys
from pathlib import Path

from ttwizard.models import Course, Meeting, Section
from ttwizard.parse_sugang import sections_from_json
from ttwizard.search import brute_force
from ttwizard.travel import TravelMatrix

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import experiments as ex  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
HUM = ex.Profile("인문대학", "국어국문학과")


def meta(remark, dept=""):
    return ex.Meta(remark=remark, dept=dept)


def test_year_of():
    assert ex.year_of("3학년") == 3 and ex.year_of("1") == 1 and ex.year_of("") is None and ex.year_of("0") == 0


def _sample_courses():
    by: dict[str, Course] = {}
    for s in sections_from_json(SAMPLE / "lectures.json"):
        by.setdefault(s.course_id, Course(s.course_id, s.course_name)).sections.append(s)
    return list(by.values())


def _sample_travel():
    return {mode: TravelMatrix.load(SAMPLE / "buildings.csv", SAMPLE / "travel.csv") for mode in ("slope", "flat")}


def test_feasible_combos_match_brute_force():
    courses = _sample_courses()
    space = ex.build_space(courses, random.Random(0))
    travel = _sample_travel()
    assert space.mode == "exact" and space.n_feasible == len(brute_force(courses, travel["slope"], "919"))


def test_rejection_sample_stays_feasible():
    courses = _sample_courses()
    cm = ex.ConflictMatrix(courses)
    groups = [[cm.index[s.key] for s in c.sections] for c in courses]
    combos = ex.rejection_sample(cm, groups, random.Random(1), 200)
    assert len(combos) == 200
    assert all(cm.ok_with(c[k], list(c[:k])) for c in combos for k in range(1, len(c)))


def test_summarize_optimum_and_real_percentile():
    courses = _sample_courses()
    travel = _sample_travel()
    space = ex.build_space(courses, random.Random(0))
    everything = brute_force(courses, travel["slope"], "919")
    best, worst = everything[0], everything[-1]
    row = ex.summarize(space, travel, "919", real=list(best.sections))
    assert row["opt_cost"] == round(best.cost, 1)
    assert row["real_percentile"] < 0.2  # 가장 좋은 조합을 골랐으면 맨 앞쪽
    assert row["cost_saving"] >= 0 and row["flat_choice_optimal"]
    row = ex.summarize(space, travel, "919", real=list(worst.sections))
    assert row["real_percentile"] > 0.8


def test_candidate_course_keeps_real_pick():
    s = Section("X1", "001", "과목", (Meeting(0, 540, 600, "25"),))
    t = Section("X1", "002", "과목", (Meeting(0, 540, 600, "301"),))
    m = {("X1", "001"): meta("®공과대학"), ("X1", "002"): meta("")}
    c = ex.candidate_course([s, t], m, HUM)
    assert [x.section_no for x in c.sections] == ["002"]
    c = ex.candidate_course([s, t], m, HUM, keep=s)
    assert sorted(x.section_no for x in c.sections) == ["001", "002"]
