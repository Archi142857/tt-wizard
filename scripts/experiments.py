"""비교 실험: 분반을 어떻게 고르느냐에 따라 주간 이동시간이 얼마나 달라지는가.

  python scripts/experiments.py                        # 기본: 가상 묶음 1,000개, 지금 학기 (2분 남짓)
  python scripts/experiments.py --bundles 500 --seed 1
  python scripts/experiments.py --real data/experiments/real_timetables.csv
  python scripts/experiments.py --no-history --no-figures

정의·방법·한계는 docs/experiments.md. 결과는 results/experiments/ (CSV, 그림, README.md 요약).

1. 분반–건물 분산  분반이 둘 이상인 학부 과목 중 분반이 서로 다른 건물에서 열리는 비율, 분반 건물 사이
                    최대 이동시간. 지난 학기 편람(data/raw/history/)으로 학기별 비율도 낸다.
2. 가상 묶음        학과·학년 전공 과목 + 수강인원이 많은 교양으로 한 학기 과목 묶음을 만들고, 그 학생이
                    들을 수 있는 분반(비고의 ® 수강 제한)만 후보로 둔다. 집 = 기숙사(919), 정문(GATE)
                    - 프로그램(1위) vs 무작위(시간이 겹치지 않는 조합 중 균등하게 하나)
                    - TSP 하한 대비, 경사를 무시하고(평지 행렬로) 고른 조합의 손해, 탐색 시간(파이썬·웹 엔진)
3. 실제 시간표      --real CSV: person,semester,college,department,course,section
                    실제로 고른 분반 vs 프로그램 vs 무작위, 실제 선택이 가능한 조합 중 몇 %에 드는지

이동시간 행렬은 웹 화면과 같은 것(export_web.export_campus)을 쓴다. 비용 = 이동시간 + 2 × 지각(분).
pandas(엑셀 읽기)와 matplotlib(그림)이 필요하다. 웹 엔진 시간은 node 가 있을 때만 잰다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import export_web  # noqa: E402
from ttwizard.bound import tsp_lower_bound  # noqa: E402
from ttwizard.conflicts import ConflictMatrix  # noqa: E402
from ttwizard.evaluate import evaluate  # noqa: E402
from ttwizard.models import Course, Section  # noqa: E402
from ttwizard.parse_sugang import _norm_section_no, parse_sugang_excel, sections_from_json  # noqa: E402
from ttwizard.search import search  # noqa: E402
from ttwizard.travel import Building, TravelMatrix  # noqa: E402
from restrictions import Student, Units, can_take  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "results" / "experiments"
HOMES = {"919": "기숙사", "GATE": "정문"}
WEEKS = 15  # 한 학기 수업 주 수 (환산용)
TOP_K = 5  # 웹 화면과 같은 값 (탐색 시간 비교용)
ENUM_CAP = 50_000  # 시간이 겹치지 않는 조합을 이 수까지 모두 센다. 넘으면 표본으로
EVAL_CAP = 20_000  # 이 수 이하면 무작위 분포를 모든 조합으로 정확히 잰다
N_SAMPLE = 4_000  # 그보다 많으면 균등 표본 수


# ---------------------------------------------------------------- 자료

@dataclass(frozen=True)
class Meta:
    """편람 엑셀에만 있는 칸 (lectures.json 에는 없다)."""

    year: str = ""  # 학년 ('1학년' …)
    college: str = ""  # 개설대학
    dept: str = ""  # 개설학과 (비어 있으면 개설대학)
    enrolled: int = 0  # 수강신청인원
    remark: str = ""  # 비고 (® 수강 제한 등)


def current_semester() -> str:
    return json.loads((DATA / "sync_state.json").read_text(encoding="utf-8")).get("semester", "")


def excel_for(sem: str) -> Path:
    """학기 편람 엑셀: 자동 갱신이 남긴 날짜별 원본(data/raw/<학기>_*.xls) 중 최신, 없으면 data/raw/history/<학기>.xls."""
    dated = sorted((DATA / "raw").glob(f"{sem}_*.xls*"))
    if dated:
        return dated[-1]
    for ext in (".xls", ".xlsx"):
        p = DATA / "raw" / "history" / f"{sem}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"{sem} 편람 엑셀이 없습니다 (data/raw/, data/raw/history/)")


def read_meta(path: Path) -> dict[tuple[str, str], Meta]:
    import pandas as pd

    raw = pd.read_excel(path, header=None, engine="xlrd" if path.suffix.lower() == ".xls" else None, dtype=str)
    h = next(i for i in range(min(len(raw), 15)) if any("교과목번호" in str(c) for c in raw.iloc[i].tolist()))
    header = [str(c).strip() for c in raw.iloc[h].tolist()]
    col = {k: next((i for i, x in enumerate(header) if k in x), None)
           for k in ("교과목번호", "강좌번호", "학년", "개설대학", "개설학과", "수강신청인원", "비고")}

    def get(row, k):
        i = col[k]
        v = None if i is None else row[i]
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return ""
        v = str(v).strip()
        return "" if v.lower() in ("nan", "none", "<na>") else v

    out: dict[tuple[str, str], Meta] = {}
    for row in raw.iloc[h + 1:].itertuples(index=False):
        cid = get(row, "교과목번호")
        if not cid:
            continue
        college = get(row, "개설대학")
        enrolled = re.sub(r"[^0-9]", "", get(row, "수강신청인원"))
        out[(cid, _norm_section_no(get(row, "강좌번호")))] = Meta(
            get(row, "학년"), college, get(row, "개설학과") or college, int(enrolled or 0), get(row, "비고"))
    return out


_cache: dict[str, tuple[list[Section], dict]] = {}


def load_semester(sem: str) -> tuple[list[Section], dict[tuple[str, str], Meta]]:
    """학기 → (분반 목록, 엑셀 칸). 지금 학기는 웹 화면과 같은 data/lectures.json 을 쓴다."""
    if sem not in _cache:
        path = excel_for(sem)
        if sem == current_semester() and (DATA / "lectures.json").exists():
            sections = sections_from_json(DATA / "lectures.json")
        else:
            sections = parse_sugang_excel(path)
        _cache[sem] = (sections, read_meta(path))
    return _cache[sem]


def timed(s: Section) -> bool:
    """학부(학사)·설강·수업시간이 있는 분반 (docs/stats 와 같은 기준)."""
    return s.program in ("", "학사") and s.status in ("", "설강") and bool(s.meetings)


def usable(s: Section) -> bool:
    """실험 후보: 거기에 더해 모든 수업의 건물이 정해진 분반. 미정 수업은 이동을 만들지 않아 최적이 그쪽으로 쏠린다."""
    return timed(s) and s.has_location


def travel_matrices() -> dict[str, TravelMatrix]:
    """웹 화면과 같은 행렬(campus.json 과 같은 값). 'slope' = 경사 반영, 'flat' = 평지."""
    campus = export_web.export_campus(DATA)
    buildings = {b: Building(b, v[0], v[1], v[2]) for b, v in campus["buildings"].items()}
    est, ids = campus["estimate"], campus["ids"]
    out = {}
    for mode in ("slope", "flat"):
        dense = campus[mode]
        table = {(a, b): dense[i][j] for i, a in enumerate(ids) for j, b in enumerate(ids)
                 if i != j and dense[i][j] is not None}
        out[mode] = TravelMatrix(buildings=buildings, table=table, walk_speed_kmh=est["walk_kmh"],
                                 detour_factor=est["detour"], default_minutes=est["default_minutes"])
    return out


# ---------------------------------------------------------------- 수강 제한 (비고의 ®, scripts/restrictions.py)

Profile = Student  # 학생: 소속 단과대(개설대학 표기)·학과(개설학과 표기)·학년(모르면 None)
_units: dict[int, Units] = {}


def units_for(meta: dict) -> Units:
    """그 학기 편람의 학과 → 단과대 사전 (비고에 나오는 이름을 알아보는 데 쓴다)."""
    if id(meta) not in _units:
        _units[id(meta)] = Units({m.dept: m.college for m in meta.values() if m.dept})
    return _units[id(meta)]


def year_of(text: str) -> int | None:
    """'3학년' / '3' → 3. 모르면 None."""
    m = re.match(r"\s*(\d)", text or "")
    return int(m.group(1)) if m else None


def eligible(row: Meta | None, profile: Student, units: Units) -> bool:
    row = row or Meta()
    return can_take(row.remark, row.dept, profile, units)


def candidate_course(sections: list[Section], meta: dict, profile: Student, keep: Section | None = None) -> Course | None:
    """과목의 분반 중 이 학생이 고를 수 있는 것만 남긴 Course. keep(실제로 고른 분반)은 늘 남긴다."""
    units = units_for(meta)
    cand = [s for s in sections if usable(s) and eligible(meta.get((s.course_id, s.section_no)), profile, units)]
    if keep is not None and keep not in cand:
        cand.append(keep)
    if not cand:
        return None
    return Course(sections[0].course_id, sections[0].course_name, cand)


# ---------------------------------------------------------------- 1. 분반–건물 분산

def pair_minutes(travel: TravelMatrix, a: str, b: str) -> float:
    return (travel.minutes(a, b) + travel.minutes(b, a)) / 2


def spread_rows(sections: list[Section], meta: dict, travel: TravelMatrix) -> list[dict]:
    by_course: dict[str, list[Section]] = {}
    for s in sections:
        if timed(s):
            by_course.setdefault(s.course_id, []).append(s)
    rows = []
    for cid, ss in by_course.items():
        if len(ss) < 2:
            continue
        bs = sorted(set().union(*(s.buildings for s in ss)))
        far = max((pair_minutes(travel, a, b) for i, a in enumerate(bs) for b in bs[i + 1:]), default=0.0)
        rows.append({
            "course_id": cid, "course_name": ss[0].course_name, "classification": ss[0].classification,
            "sections": len(ss), "sections_located": sum(s.has_location for s in ss),
            "buildings": len(bs), "building_list": " ".join(bs),
            "max_minutes": round(far, 3),
            "enrolled": sum(meta.get((s.course_id, s.section_no), Meta()).enrolled for s in ss),
        })
    return sorted(rows, key=lambda r: (-r["buildings"], -r["max_minutes"], r["course_name"]))


def spread_summary(rows: list[dict]) -> list[dict]:
    groups = {"전체": rows}
    for cls in ("교양", "전필", "전선"):
        groups[cls] = [r for r in rows if r["classification"] == cls]
    out = []
    for name, rs in groups.items():
        located = [r for r in rs if r["buildings"] >= 1]
        multi = [r for r in located if r["buildings"] >= 2]
        stud = sum(r["enrolled"] for r in located)
        stud_multi = sum(r["enrolled"] for r in multi)
        out.append({
            "group": name, "courses": len(rs), "courses_located": len(located), "courses_multi_building": len(multi),
            "ratio": round(len(multi) / len(located), 3) if located else "",  # 건물을 아는 과목 중
            "ratio_all": round(len(multi) / len(rs), 3) if rs else "",  # 강의실 미정 과목까지 분모에 (docs/stats 기준)
            "enrolled": stud, "enrolled_multi_building": stud_multi,
            "ratio_enrolled": round(stud_multi / stud, 3) if stud else "",
            "median_max_minutes": round(statistics.median(r["max_minutes"] for r in multi), 1) if multi else "",
        })
    return out


def spread_by_semester(current: str) -> list[dict]:
    """학기별 분반–건물 분산 비율. 지난 학기는 data/raw/history/ (학기가 끝난 뒤 받은 편람이라 강의실이 거의 다 찼다).

    ratio_located(건물을 아는 과목 중)가 학기끼리 견줄 수 있는 값이다. ratio_all 은 location_stats·docs/stats 와 같은
    정의(강의실 미정 과목까지 분모)라 강의실이 덜 찬 지금 학기는 낮게 나온다.
    """
    files = {p.stem: p for p in sorted((DATA / "raw" / "history").glob("*.xls*"))}
    try:
        files[current] = excel_for(current)
    except FileNotFoundError:
        pass
    rows = []
    for sem in sorted(files, key=semester_key):
        by_course: dict[str, list[Section]] = {}
        for s in parse_sugang_excel(files[sem]):
            if timed(s):
                by_course.setdefault(s.course_id, []).append(s)
        multi = [ss for ss in by_course.values() if len(ss) >= 2]
        nb = [len(set().union(*(s.buildings for s in ss))) for ss in multi]
        located, spread = sum(n >= 1 for n in nb), sum(n >= 2 for n in nb)
        rows.append({"semester": sem, "regular": sem[-1] in "12", "courses_multi_section": len(multi),
                     "courses_located": located, "courses_multi_building": spread,
                     "ratio_located": round(spread / located, 3) if located else "",
                     "ratio_all": round(spread / len(multi), 3) if multi else ""})
        print(f"  {sem}: 복수 분반 {len(multi)}개, 건물을 아는 {located}개 중 {pct(rows[-1]['ratio_located'])}")
    return rows


def semester_key(sem: str) -> tuple[int, int]:
    year, term = sem.split("-")
    return int(year), "1S2W".index(term)


# ---------------------------------------------------------------- 2·3. 조합 분석

def feasible_combos(cm: ConflictMatrix, groups: list[list[int]], cap: int) -> tuple[list[tuple[int, ...]], bool]:
    """시간이 겹치지 않는 조합(분반 전역 인덱스 튜플)을 cap 개까지. (목록, 다 셌는지)."""
    out: list[tuple[int, ...]] = []
    chosen: list[int] = []

    def rec(d: int) -> bool:
        if d == len(groups):
            out.append(tuple(chosen))
            return len(out) < cap
        for i in groups[d]:
            if cm.ok_with(i, chosen):
                chosen.append(i)
                go = rec(d + 1)
                chosen.pop()
                if not go:
                    return False
        return True

    complete = rec(0)
    return out, complete


def rejection_sample(cm: ConflictMatrix, groups: list[list[int]], rng: random.Random, n: int,
                     max_tries: int = 3_000_000) -> list[tuple[int, ...]]:
    """분반을 과목마다 균등하게 뽑고 겹치면 버린다 → 시간이 겹치지 않는 조합 위의 균등 표본."""
    out: list[tuple[int, ...]] = []
    for _ in range(max_tries):
        combo = [rng.choice(g) for g in groups]
        if all(cm.ok_with(combo[k], combo[:k]) for k in range(1, len(combo))):
            out.append(tuple(combo))
            if len(out) >= n:
                break
    return out


@dataclass
class Space:
    """한 과목 묶음의 조합 공간과 무작위 분포용 조합들."""

    courses: list[Course]
    cm: ConflictMatrix
    n_combinations: int
    n_feasible: int | None  # None = ENUM_CAP 이상
    mode: str  # exact / sample
    combos: list[tuple[int, ...]] = field(default_factory=list)


def build_space(courses: list[Course], rng: random.Random) -> Space:
    cm = ConflictMatrix(courses)
    groups = [[cm.index[s.key] for s in c.sections] for c in courses]
    n_comb = math.prod(len(g) for g in groups)
    combos, complete = feasible_combos(cm, groups, ENUM_CAP)
    if complete and len(combos) <= EVAL_CAP:
        return Space(courses, cm, n_comb, len(combos), "exact", combos)
    if complete:
        return Space(courses, cm, n_comb, len(combos), "sample", rng.sample(combos, N_SAMPLE))
    return Space(courses, cm, n_comb, None, "sample", rejection_sample(cm, groups, rng, N_SAMPLE))


def group_twins(courses: list[Course]) -> list[Course]:
    """시간·건물이 모두 같은 분반은 하나만 남긴다. 웹 화면(app.js groupSections)이 탐색 전에 하는 것과 같다.
    1위 비용은 그대로이고 탐색만 빨라진다. 무작위 분포는 분반 단위로 재야 하므로 여기에 쓰지 않는다."""
    out = []
    for c in courses:
        seen: dict[tuple, Section] = {}
        for s in c.sections:
            seen.setdefault(tuple(sorted((m.day, m.start, m.end, m.building) for m in s.meetings)), s)
        out.append(Course(c.course_id, c.name, list(seen.values())))
    return out


def summarize(space: Space, travel: dict[str, TravelMatrix], home: str, real: list[Section] | None = None) -> dict:
    slope, flat = travel["slope"], travel["flat"]
    evs = [evaluate([space.cm.sections[i] for i in combo], slope, home) for combo in space.combos]
    tr = [e.travel_minutes for e in evs]
    grouped = group_twins(space.courses)
    t0 = time.perf_counter()
    res = search(grouped, slope, home, top_k=TOP_K)
    py_ms = (time.perf_counter() - t0) * 1000
    best = res.ranked[0]
    flat_best = search(grouped, flat, home, top_k=1).ranked[0]
    flat_on_slope = evaluate(flat_best.sections, slope, home)
    best_on_flat = evaluate(best.sections, flat, home)
    lb = tsp_lower_bound(grouped, slope, home)
    rand_travel, rand_cost = statistics.fmean(tr), statistics.fmean(e.cost for e in evs)
    row = {
        "home": home, "n_courses": len(space.courses), "n_sections": sum(len(c.sections) for c in space.courses),
        "n_combinations": space.n_combinations,
        "n_combinations_grouped": math.prod(len(c.sections) for c in grouped),  # 웹 화면이 실제로 뒤지는 공간
        "n_feasible": space.n_feasible if space.n_feasible is not None else f">={ENUM_CAP}",
        # 분반에 따라 비용이 달라지는가 (시간이 안 겹치는 조합이 여럿이어도 비용이 모두 같으면 고를 게 없다)
        "has_choice": max(e.cost for e in evs) - min(e.cost for e in evs) > 0.05,
        "random_mode": space.mode, "random_n": len(evs),
        "opt_travel": round(best.travel_minutes, 1), "opt_late": round(best.late_minutes, 1), "opt_cost": round(best.cost, 1),
        "random_travel_mean": round(rand_travel, 1), "random_travel_median": round(statistics.median(tr), 1),
        "random_travel_max": round(max(tr), 1) if space.mode == "exact" else "",
        "random_late_share": round(sum(e.late_minutes > 0 for e in evs) / len(evs), 3),
        "random_late_mean": round(statistics.fmean(e.late_minutes for e in evs), 1),
        "random_cost_mean": round(rand_cost, 1),
        # 이동시간 절약. 1위는 지각까지 넣은 비용을 줄이므로, 지각이 있는 무작위 조합보다 이동은 길 수도 있다(음수)
        "saving": round(rand_travel - best.travel_minutes, 1),
        "saving_ratio": round(1 - best.travel_minutes / rand_travel, 3) if rand_travel else 0.0,
        "cost_saving": round(rand_cost - best.cost, 1),  # 비용(이동 + 2 × 지각) 기준, 늘 0 이상
        "lower_bound": round(lb, 1), "opt_over_bound": round(best.travel_minutes / lb, 3) if lb else "",
        "flat_choice_travel": round(flat_on_slope.travel_minutes, 1),
        # 평지 행렬로 고른 1위를 경사 반영 비용으로 쟀을 때 경사 반영 1위보다 더 드는 비용. 0 이면 같은 답(동점 포함)
        "slope_loss": round(flat_on_slope.cost - best.cost, 2),
        "flat_choice_optimal": round(flat_on_slope.cost - best.cost, 2) < 0.05,  # 적힌 값(slope_loss)과 맞춘다
        "opt_travel_flat": round(best_on_flat.travel_minutes, 1),
        "slope_extra": round(best.travel_minutes / best_on_flat.travel_minutes - 1, 3) if best_on_flat.travel_minutes else "",
        "py_ms": round(py_ms, 3), "py_leaves": res.stats.leaves, "py_nodes": res.stats.nodes,
        "best_sections": " ".join(s.key for s in best.sections),
    }
    if real is not None:
        ev = evaluate(real, slope, home)
        costs = [e.cost for e in evs]
        below = sum(c < ev.cost - 1e-9 for c in costs)
        ties = sum(abs(c - ev.cost) <= 1e-9 for c in costs)
        row.update({
            "real_travel": round(ev.travel_minutes, 1), "real_late": round(ev.late_minutes, 1), "real_cost": round(ev.cost, 1),
            "real_percentile": round((below + ties / 2) / len(costs), 3),  # 0 = 가장 좋은 쪽, 1 = 가장 나쁜 쪽
            "real_saving": round(ev.travel_minutes - best.travel_minutes, 1),
            "real_sections": " ".join(s.key for s in real),
        })
    return row


# ---------------------------------------------------------------- 2. 가상 묶음

@dataclass
class Bundle:
    bid: int
    profile: Profile
    year: str
    courses: list[Course]


def make_bundles(n: int, rng: random.Random, sections: list[Section], meta: dict) -> list[Bundle]:
    """학과·학년 전공 과목 + 교양으로 한 학기 묶음을 만든다 (docs/experiments.md 2절).

    - 코호트(개설대학, 개설학과, 학년 1~4)를 고르게 하나 뽑는다. 전공(전필·전선) 과목이 2개 이상인 코호트만
    - 과목 수 5~6개. 전공은 1학년 2개, 2학년 이상 4개(코호트에 그만큼 없으면 있는 만큼), 나머지는 교양
    - 교양은 그 학생이 들을 수 있는 분반의 수강인원 합에 비례해 뽑는다 → 많이 듣는 대학 글쓰기·영어·과학 실험이
      자주 나오고, 다른 단과대 몫으로 묶인 분반(®)은 무게에 넣지 않는다
    - 각 과목은 그 학생이 고를 수 있는 분반만 남긴다. 시간이 겹치지 않는 조합이 하나도 없으면 다시 뽑는다
    """
    by_course: dict[str, list[Section]] = {}
    for s in sections:
        if timed(s):
            by_course.setdefault(s.course_id, []).append(s)
    first = {cid: meta.get((ss[0].course_id, ss[0].section_no), Meta()) for cid, ss in by_course.items()}
    cohorts: dict[tuple[str, str, str], list[str]] = {}
    gened: list[str] = []
    for cid, ss in by_course.items():
        m = first[cid]
        if ss[0].classification in ("전필", "전선") and m.year in ("1학년", "2학년", "3학년", "4학년"):
            cohorts.setdefault((m.college, m.dept, m.year), []).append(cid)
        elif ss[0].classification == "교양":
            gened.append(cid)
    keys = sorted(k for k, v in cohorts.items() if len(v) >= 2)
    weights: dict[Profile, dict[str, int]] = {}
    units = units_for(meta)

    def gened_weights(profile: Profile) -> dict[str, int]:
        if profile not in weights:
            w = {}
            for cid in gened:
                ms = [meta.get((s.course_id, s.section_no)) for s in by_course[cid] if usable(s)]
                w[cid] = sum(m.enrolled for m in ms if m and eligible(m, profile, units))
            weights[profile] = {cid: v for cid, v in w.items() if v > 0}
        return weights[profile]

    bundles: list[Bundle] = []
    for _ in range(n * 50):
        if len(bundles) >= n:
            break
        college, dept, year = rng.choice(keys)
        profile = Profile(college, dept, year_of(year))
        weight = gened_weights(profile)
        majors = [c for c in (candidate_course(by_course[cid], meta, profile) for cid in cohorts[(college, dept, year)]) if c]
        n_major = min(len(majors), 2 if year == "1학년" else 4)
        if n_major == 0:
            continue
        for _attempt in range(30):
            picked = rng.sample(majors, n_major)
            target = rng.choice((5, 6))
            pool = list(weight)
            while len(picked) < target and pool:
                cid = rng.choices(pool, weights=[weight[c] for c in pool])[0]
                pool.remove(cid)
                c = candidate_course(by_course[cid], meta, profile)
                if c:
                    picked.append(c)
            cm = ConflictMatrix(picked)
            combos, _ = feasible_combos(cm, [[cm.index[s.key] for s in c.sections] for c in picked], 1)
            if combos:
                bundles.append(Bundle(len(bundles) + 1, profile, year, picked))
                break
    return bundles


# ---------------------------------------------------------------- 웹 엔진 시간

def js_times(cases: list[dict]) -> list[dict] | None:
    """scripts/engine_bench.mjs 로 웹 엔진(engine.js) 탐색 시간을 잰다. node 가 없으면 None."""
    if shutil.which("node") is None or not cases:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        campus, path = Path(tmp) / "campus.json", Path(tmp) / "cases.json"
        campus.write_text(json.dumps(export_web.export_campus(DATA), ensure_ascii=False), encoding="utf-8")
        path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        run = subprocess.run(["node", str(ROOT / "scripts" / "engine_bench.mjs"), str(campus), str(path)],
                             capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(run.stdout)


def js_case(courses: list[Course], home: str) -> dict:
    return {"home": home, "mode": "slope", "topK": TOP_K,
            "courses": [[c.course_id, [[s.section_no, [[m.day, m.start, m.end, m.building] for m in s.meetings]]
                                       for s in c.sections]] for c in courses]}


def stress_rows(sections: list[Section], meta: dict, travel: dict[str, TravelMatrix], ks=range(4, 9), py_max: int = 6) -> list[dict]:
    """부하 시험: 수강인원이 가장 많은 교양 k개(대학 글쓰기·수학·물리 …)를 모든 분반 그대로 담았을 때의 탐색 시간.

    웹 화면은 수강 제한을 모르므로 분반을 끄지 않으면 이 상태로 찾는다(이공계 1학년 기초 과목을 한꺼번에 담은 경우).
    웹 엔진은 k 전부, 파이썬은 오래 걸려 k ≤ py_max 만 잰다. 집 = 기숙사(919).
    """
    by_course: dict[str, list[Section]] = {}
    for s in sections:
        if usable(s):
            by_course.setdefault(s.course_id, []).append(s)
    gened = [cid for cid, ss in by_course.items() if ss[0].classification == "교양"]
    enrolled = {cid: sum(meta.get((s.course_id, s.section_no), Meta()).enrolled for s in by_course[cid]) for cid in gened}
    top = sorted(gened, key=lambda cid: -enrolled[cid])[:max(ks)]
    rows, cases = [], []
    for k in ks:
        grouped = group_twins([Course(cid, by_course[cid][0].course_name, by_course[cid]) for cid in top[:k]])
        row = {"k": k, "courses": " | ".join(c.name for c in grouped),
               "sections": " ".join(str(len(c.sections)) for c in grouped),
               "n_combinations_grouped": math.prod(len(c.sections) for c in grouped), "py_ms": "", "py_leaves": ""}
        if k <= py_max:
            t0 = time.perf_counter()
            res = search(grouped, travel["slope"], "919", top_k=TOP_K)
            row.update(py_ms=round((time.perf_counter() - t0) * 1000, 1), py_leaves=res.stats.leaves,
                       opt_cost=round(res.ranked[0].cost, 1) if res.ranked else "")
        rows.append(row)
        cases.append(js_case(grouped, "919"))
    for row, t in zip(rows, js_times(cases) or []):
        row.update(js_ms=round(t["ms"], 1), js_leaves=t["leaves"])
        print(f"  교양 {row['k']}개: 조합 {row['n_combinations_grouped']:.1e}, 웹 엔진 {row['js_ms']:,.0f} ms"
              + (f", 파이썬 {row['py_ms']:,.0f} ms" if row["py_ms"] != "" else ""))
    return rows


# ---------------------------------------------------------------- 3. 실제 시간표

def read_real(path: Path, current: str) -> dict[str, dict]:
    people: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("person") or not r.get("course"):
                continue
            p = people.setdefault(r["person"], {"semester": r.get("semester") or current, "college": r.get("college", ""),
                                                "department": r.get("department", ""), "year": r.get("year", ""),
                                                "picks": []})
            p["picks"].append((r["course"], _norm_section_no(r.get("section", ""))))
    return people


def find_course(by_course: dict[str, list[Section]], text: str) -> str:
    if text in by_course:
        return text
    hits = [cid for cid, ss in by_course.items() if ss[0].course_name == text or ss[0].course_name.split(" (")[0] == text]
    if len(hits) != 1:
        raise ValueError(f"과목 '{text}'를 {'찾지 못했습니다' if not hits else f'하나로 정하지 못했습니다 {hits}'} — 교과목번호로 적어 주세요")
    return hits[0]


def real_rows(path: Path, travel: dict, rng: random.Random, current: str) -> list[dict]:
    rows = []
    for person, p in read_real(path, current).items():
        sections, meta = load_semester(p["semester"])
        by_course: dict[str, list[Section]] = {}
        for s in sections:
            if timed(s):
                by_course.setdefault(s.course_id, []).append(s)
        profile = Profile(p["college"], p["department"] or p["college"], year_of(p["year"]))
        courses, chosen, notes = [], [], []
        for text, no in p["picks"]:
            cid = find_course(by_course, text)
            sec = next((s for s in by_course[cid] if s.section_no == no), None)
            if sec is None:
                raise ValueError(f"{person}: {text} {no}분반이 {p['semester']} 편람에 없습니다")
            if not sec.has_location:
                notes.append(f"{sec.course_name} 강의실 미정")
            c = candidate_course(by_course[cid], meta, profile, keep=sec)
            courses.append(c)
            chosen.append(sec)
        notes += [f"시간 겹침: {a.course_name} {a.section_no} – {b.course_name} {b.section_no}"
                  for i, a in enumerate(chosen) for b in chosen[i + 1:] if a.conflicts_with(b)]
        known = {a for a, _ in travel["slope"].table}
        missing = sorted({b for c in courses for s in c.sections for b in s.buildings} - known)
        if missing:
            notes.append("행렬에 없는 건물(좌표로 추정): " + " ".join(missing))
        space = build_space(courses, rng)
        for home in HOMES:
            row = summarize(space, travel, home, real=chosen)
            rows.append({"person": person, "semester": p["semester"], "college": p["college"],
                         "department": p["department"], "courses": " | ".join(c.name for c in courses),
                         "note": "; ".join(notes), **row})
        print(f"  {person} ({p['semester']}): 실제 {rows[-2]['real_travel']}분 / 1위 {rows[-2]['opt_travel']}분 "
              f"/ 무작위 평균 {rows[-2]['random_travel_mean']}분")
    return rows


# ---------------------------------------------------------------- 출력

def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def q(values: list[float], p: float) -> float:
    values = sorted(values)
    if not values:
        return float("nan")
    k = (len(values) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def ci95(xs: list[float]) -> tuple[float, float]:
    m = statistics.fmean(xs)
    h = 1.96 * statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0
    return m - h, m + h


def bundle_summary(rows: list[dict]) -> list[dict]:
    out = []
    for home, label in HOMES.items():
        rs = [r for r in rows if r["home"] == home]
        if not rs:
            continue
        choice = [r for r in rs if r["has_choice"]]
        sav = [r["saving"] for r in rs]
        sav_c = [r["saving"] for r in choice] or [0.0]
        ratio = [r["opt_over_bound"] for r in rs if r["opt_over_bound"] != ""]
        extra = [r["slope_extra"] for r in rs if r["slope_extra"] != ""]
        js = [r["js_ms"] for r in rs if r.get("js_ms") not in (None, "")]
        changed = [r for r in rs if not r["flat_choice_optimal"]]
        items = [
            ("묶음 수", len(rs), "개"),
            ("분반에 따라 비용이 달라지는 묶음", round(len(choice) / len(rs), 3), "비율"),
            ("무작위 주간 이동시간 (묶음 중앙값)", round(q([r["random_travel_mean"] for r in rs], 0.5), 1), "분/주"),
            ("프로그램 1위 주간 이동시간 (묶음 중앙값)", round(q([r["opt_travel"] for r in rs], 0.5), 1), "분/주"),
            ("이동시간 절약 (평균)", round(statistics.fmean(sav), 1), "분/주"),
            # 묶음을 새로 뽑으면 평균이 이만큼 흔들린다 (평균 ± 1.96 × 표준오차)
            ("이동시간 절약 평균의 95% 구간", "{:.1f}–{:.1f}".format(*ci95(sav)), "분/주"),
            ("이동시간 절약 (중앙값)", round(q(sav, 0.5), 1), "분/주"),
            ("이동시간 절약 (90% 분위: 이보다 많이 주는 묶음이 10%)", round(q(sav, 0.9), 1), "분/주"),
            ("이동시간 절약 (절약이 가장 큰 10% 묶음의 평균)", round(statistics.fmean(sorted(sav)[-max(1, len(sav) // 10):]), 1), "분/주"),
            ("이동시간 절약 (비용이 달라지는 묶음 평균)", round(statistics.fmean(sav_c), 1), "분/주"),
            ("이동시간 절약률 (평균)", round(statistics.fmean(r["saving_ratio"] for r in rs), 3), "비율"),
            (f"한 학기({WEEKS}주) 절약 (평균)", round(statistics.fmean(sav) * WEEKS / 60, 1), "시간"),
            ("비용(이동 + 2×지각) 절약 (평균)", round(statistics.fmean(r["cost_saving"] for r in rs), 1), "분/주"),
            ("무작위 조합에 지각 구간이 있을 확률 (평균)", round(statistics.fmean(r["random_late_share"] for r in rs), 3), "비율"),
            ("1위에 지각 구간이 있는 묶음", round(sum(r["opt_late"] > 0 for r in rs) / len(rs), 3), "비율"),
            ("1위 ÷ TSP 하한 (중앙값)", round(q(ratio, 0.5), 2) if ratio else "", "배"),
            ("경사 반영이 1위 이동시간을 늘리는 정도 (중앙값)", round(q(extra, 0.5), 3) if extra else "", "비율"),
            ("평지 기준으로 고르면 경사 반영 1위가 아닌 묶음", round(len(changed) / len(rs), 3), "비율"),
            ("그때 더 드는 비용 (평균)", round(statistics.fmean(r["slope_loss"] for r in changed), 1) if changed else 0.0, "분/주"),
            ("탐색 시간 파이썬 (중앙값)", round(q([r["py_ms"] for r in rs], 0.5), 1), "ms"),
            ("탐색 시간 파이썬 (최대)", round(max(r["py_ms"] for r in rs), 1), "ms"),
            ("탐색 시간 웹 엔진 (중앙값)", round(q(js, 0.5), 1) if js else "", "ms"),
            ("탐색 시간 웹 엔진 (최대)", round(max(js), 1) if js else "", "ms"),
            ("이론상 조합 수 (최대, 같은 시간·건물 분반을 묶은 뒤)", max(r["n_combinations_grouped"] for r in rs), "개"),
        ]
        out += [{"home": home, "home_label": label, "metric": m, "value": v, "unit": u} for m, v, u in items]
    return out


def write_readme(path: Path, args, sem: str, summary: list[dict], spread: list[dict], semesters: list[dict],
                 stress: list[dict], real: list[dict], figures: list[str]) -> None:
    lines = [
        "# 비교 실험 결과",
        "",
        f"`python scripts/experiments.py --bundles {args.bundles} --seed {args.seed}` 로 만든 파일이다 "
        f"({time.strftime('%Y-%m-%d %H:%M')}, 편람 {sem}). 정의와 방법은 `docs/experiments.md`.",
        "이동시간은 캠퍼스 마법 지도 표 × 경사 계수로 추정한 값이고 실측이 아니다.",
        "",
        "## 1. 분반–건물 분산 (학부, 분반 둘 이상인 과목)",
        "",
        "| 구분 | 건물을 아는 과목 | 여러 건물에 흩어진 과목 | 비율 | 수강인원 가중 비율 | 가장 먼 두 건물 (중앙값) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in spread:
        lines.append(f"| {r['group']} | {r['courses_located']} | {r['courses_multi_building']} | {pct(r['ratio'])} | "
                     f"{pct(r['ratio_enrolled'])} | {r['median_max_minutes']}분 |")
    if semesters:
        reg = [r for r in semesters if r["regular"]]
        lo, hi = min(reg, key=lambda r: r["ratio_located"]), max(reg, key=lambda r: r["ratio_located"])
        lines += ["", f"정규학기 {reg[0]['semester']}~{reg[-1]['semester']} ({len(reg)}개 학기, 건물을 아는 과목 기준): "
                      f"{pct(lo['ratio_located'])}({lo['semester']}) ~ {pct(hi['ratio_located'])}({hi['semester']}). "
                      "`spread_by_semester.csv`."]
    lines += ["", "## 2. 가상 묶음: 프로그램 vs 무작위", "",
              "| 항목 | 기숙사(919) | 정문(GATE) | 단위 |", "| --- | --- | --- | --- |"]
    metrics = list(dict.fromkeys(r["metric"] for r in summary))
    for m in metrics:
        v = {r["home"]: r for r in summary if r["metric"] == m}
        unit = v["919"]["unit"]
        fmt = (lambda x: pct(x)) if unit == "비율" else (lambda x: f"{x:,}" if isinstance(x, (int, float)) else x)
        lines.append(f"| {m} | {fmt(v['919']['value'])} | {fmt(v['GATE']['value']) if 'GATE' in v else ''} | "
                     f"{'' if unit == '비율' else unit} |")
    if stress:
        lines += ["", "## 2b. 부하 시험: 수강인원이 가장 많은 교양 k개를 모든 분반 그대로", "",
                  "웹 화면에서 분반을 끄지 않고 담았을 때와 같다. 시간은 이 컴퓨터의 node 기준이라 폰에서는 몇 배 걸릴 수 있다.", "",
                  "| k | 과목 | 조합 수 (묶은 뒤) | 웹 엔진 | 파이썬 |", "| --- | --- | --- | --- | --- |"]
        for i, r in enumerate(stress):
            names = r["courses"].split(" | ")
            what = ", ".join(names) if i == 0 else "+ " + names[-1]
            py = f"{r['py_ms']:,.0f} ms" if r["py_ms"] != "" else "–"
            lines.append(f"| {r['k']} | {what} | {r['n_combinations_grouped']:.1e} | {r.get('js_ms', 0):,.0f} ms | {py} |")
    if real:
        lines += ["", "## 3. 실제 시간표", "",
                  "| 사람 | 학기 | 집 | 실제 | 프로그램 1위 | 무작위 평균 | 실제 선택의 위치 |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in real:
            lines.append(f"| {r['person']} | {r['semester']} | {HOMES[r['home']]} | {r['real_travel']}분 | {r['opt_travel']}분 | "
                         f"{r['random_travel_mean']}분 | 상위 {pct(r['real_percentile'])} |")
    lines += ["", "## 파일", "",
              "| 파일 | 내용 |", "| --- | --- |",
              "| `spread_courses.csv` | 과목별 분반 수, 건물 수, 가장 먼 두 건물 사이 시간(분, 두 방향 평균), 수강인원 |",
              "| `spread_summary.csv` | 교과구분별 요약 |",
              "| `spread_by_semester.csv` | 학기별 분반–건물 분산 비율 |",
              "| `bundles.csv` | 가상 묶음 × 집별 결과 (열 설명은 docs/experiments.md) |",
              "| `summary.csv` | 위 2절 표 |",
              "| `stress.csv` | 부하 시험 |"]
    if real:
        lines.append("| `real.csv` | 실제 시간표별 결과 |")
    lines += [f"| `{f}.png`, `{f}.svg` | {FIGURE_TITLES[f]} |" for f in figures]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pct(x) -> str:
    return "" if x in ("", None) else f"{float(x) * 100:.1f}%"


# ---------------------------------------------------------------- 그림

INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
FIGURE_TITLES = {
    "fig1_spread": "교과구분별 분반–건물 분산 비율, 가장 먼 두 건물 사이 시간 분포",
    "fig2_semesters": "학기별 분반–건물 분산 비율",
    "fig3_saving": "무작위 대비 프로그램 1위의 주간 이동시간 절약 (묶음별)",
    "fig4_opt_vs_random": "무작위 평균 vs 프로그램 1위 주간 이동시간 (묶음별)",
    "fig5_bound": "프로그램 1위 ÷ TSP 하한",
    "fig6_search_time": "조합 수와 탐색 시간 (파이썬, 웹 엔진)",
    "fig7_real": "실제 시간표: 실제 선택, 프로그램 1위, 무작위 평균",
}


def pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    have = {f.name for f in font_manager.fontManager.ttflist}
    for fam in ("Malgun Gothic", "Apple SD Gothic Neo", "AppleGothic", "NanumGothic", "Noto Sans KR",
                "Noto Sans CJK KR", "Noto Sans CJK JP"):
        if fam in have:
            plt.rcParams["font.family"] = fam
            break
    plt.rcParams.update({
        "axes.unicode_minus": False, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK2, "axes.titlecolor": INK,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 10,
        "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 9, "ytick.labelsize": 9,
        "text.color": INK, "font.size": 9.5, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "legend.frameon": False, "svg.fonttype": "none",
    })
    return plt


def save(fig, out: Path, name: str, done: list[str]) -> None:
    for ext in ("png", "svg"):
        fig.savefig(out / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    done.append(name)


def figures(out: Path, spread_rows_: list[dict], spread_sum: list[dict], semesters: list[dict], bundles: list[dict],
            real: list[dict]) -> list[str]:
    plt = pyplot()
    done: list[str] = []

    # 1. 교과구분별 비율 + 가장 먼 두 건물 분포
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.2), gridspec_kw={"width_ratios": [1, 1.2], "wspace": 0.35})
    groups = [r for r in spread_sum if r["courses_located"]][::-1]
    ys = range(len(groups))
    a.barh(ys, [r["ratio"] * 100 for r in groups], height=0.45, color=C1)
    a.set_yticks(list(ys), [r["group"] for r in groups])
    a.tick_params(axis="y", length=0)
    for y, r in zip(ys, groups):
        a.text(r["ratio"] * 100 + 1.5, y, f"{r['ratio'] * 100:.0f}%  ({r['courses_multi_building']}/{r['courses_located']})",
               va="center", fontsize=8.5, color=INK2)
    a.set_xlim(0, 100)
    a.set_xlabel("분반이 여러 건물에 흩어진 과목 비율 (%)")
    a.grid(axis="y", visible=False)
    a.set_title("분반이 둘 이상인 학부 과목")
    far = [r["max_minutes"] for r in spread_rows_ if r["buildings"] >= 2]
    b.hist(far, bins=range(0, int(max(far)) + 3, 2), color=C1, edgecolor=SURFACE, linewidth=1.2)
    b.axvline(statistics.median(far), color=INK2, linewidth=1)
    b.text(statistics.median(far) + 0.4, b.get_ylim()[1] * 0.92, f"중앙값 {statistics.median(far):.1f}분", fontsize=8.5, color=INK2)
    b.set_xlabel("분반 건물 가운데 가장 먼 두 곳 사이 (분, 경사 반영)")
    b.set_ylabel("과목 수")
    b.grid(axis="x", visible=False)
    b.set_title(f"흩어진 과목 {len(far)}개는 얼마나 떨어져 있나")
    save(fig, out, "fig1_spread", done)
    plt.close(fig)

    # 2. 학기별 비율
    if semesters:
        reg = [r for r in semesters if r["regular"]]
        fig, ax = plt.subplots(figsize=(7, 2.8))
        xs = range(len(reg))
        ax.plot(xs, [r["ratio_located"] * 100 for r in reg], color=C1, linewidth=2, marker="o", markersize=5,
                markeredgecolor=SURFACE, markeredgewidth=1.5)
        ax.set_xticks(list(xs), [r["semester"] for r in reg], rotation=0)
        ax.set_ylim(0, 100)
        ax.set_ylabel("여러 건물에 흩어진 과목 (%)")
        ax.set_title("학기별 분반–건물 분산 비율 (정규학기, 학부, 건물을 아는 과목 중)")
        last = reg[-1]
        ax.annotate(f"{last['ratio_located'] * 100:.0f}%", (len(reg) - 1, last["ratio_located"] * 100),
                    textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8.5, color=INK2)
        save(fig, out, "fig2_semesters", done)
        plt.close(fig)

    dorm = [r for r in bundles if r["home"] == "919"]
    if dorm:
        # 3. 절약 분포
        sav = [r["saving"] for r in dorm]
        fig, ax = plt.subplots(figsize=(7, 3))
        lo, top = min(0, math.floor(min(sav) / 5) * 5), max(10, math.ceil(max(sav) / 5) * 5)
        ax.hist(sav, bins=range(lo, top + 5, 5), color=C1, edgecolor=SURFACE, linewidth=1.2)
        med = statistics.median(sav)
        ax.axvline(med, color=INK2, linewidth=1)
        ax.text(med + 1, ax.get_ylim()[1] * 0.9, f"중앙값 {med:.0f}분/주", fontsize=8.5, color=INK2)
        ax.set_xlabel("무작위 평균 − 프로그램 1위 (분/주)")
        ax.set_ylabel("묶음 수")
        ax.grid(axis="x", visible=False)
        ax.set_title(f"분반을 프로그램으로 고르면 주간 이동시간이 얼마나 주나 (가상 묶음 {len(dorm):,}개, 기숙사 출발)")
        save(fig, out, "fig3_saving", done)
        plt.close(fig)

        # 4. 무작위 평균 vs 1위
        fig, ax = plt.subplots(figsize=(4.6, 4.4))
        xs = [r["random_travel_mean"] for r in dorm]
        ys = [r["opt_travel"] for r in dorm]
        hi = math.ceil(max(xs + ys) / 20) * 20
        ax.plot([0, hi], [0, hi], color=AXIS, linewidth=1)
        ax.text(hi * 0.62, hi * 0.66, "같음", color=MUTED, fontsize=8.5, rotation=45)
        ax.scatter(xs, ys, s=22, color=C1, edgecolor=SURFACE, linewidth=1, alpha=0.9)
        ax.set_xlim(0, hi)
        ax.set_ylim(0, hi)
        ax.set_xlabel("무작위로 고를 때 평균 (분/주)")
        ax.set_ylabel("프로그램 1위 (분/주)")
        ax.set_title("묶음별 주간 이동시간 (기숙사 출발)")
        save(fig, out, "fig4_opt_vs_random", done)
        plt.close(fig)

        # 5. 하한 대비
        ratio = [r["opt_over_bound"] for r in dorm if r["opt_over_bound"] != ""]
        if ratio:
            fig, ax = plt.subplots(figsize=(7, 2.8))
            ax.hist(ratio, bins=[1 + 0.25 * i for i in range(int((max(ratio) - 1) / 0.25) + 2)], color=C1,
                    edgecolor=SURFACE, linewidth=1.2)
            ax.set_xlabel("프로그램 1위 ÷ TSP 하한 (배)")
            ax.set_ylabel("묶음 수")
            ax.grid(axis="x", visible=False)
            ax.set_title("이론상 최소(모든 과목을 한 번씩 도는 가장 짧은 길) 대비 (기숙사 출발)")
            save(fig, out, "fig5_bound", done)
            plt.close(fig)

        # 6. 탐색 시간
        fig, ax = plt.subplots(figsize=(6, 3.6))
        comb = [r["n_combinations_grouped"] for r in bundles]
        ax.scatter(comb, [max(r["py_ms"], 0.01) for r in bundles], s=16, color=C1, edgecolor=SURFACE, linewidth=0.8,
                   label="파이썬 (ttwizard)")
        js = [(r["n_combinations_grouped"], r["js_ms"]) for r in bundles if r.get("js_ms") not in (None, "")]
        if js:
            ax.scatter([c for c, _ in js], [max(m, 0.01) for _, m in js], s=16, color=C2, edgecolor=SURFACE,
                       linewidth=0.8, label="웹 엔진 (engine.js, node)")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("이론상 조합 수 (같은 시간·건물 분반을 하나로 묶은 뒤 분반 수의 곱)")
        ax.set_ylabel("탐색 시간 (ms)")
        ax.legend(loc="upper left", fontsize=8.5)
        ax.set_title(f"탐색 시간 (상위 {TOP_K}개, 분기 한정, 묶음 {len(bundles) // len(HOMES):,}개 × 출발지 {len(HOMES)}곳)")
        save(fig, out, "fig6_search_time", done)
        plt.close(fig)

    if real:
        rs = [r for r in real if r["home"] == "919"] or real
        fig, ax = plt.subplots(figsize=(6.5, 0.5 * len(rs) + 1.4))
        ys = list(range(len(rs)))[::-1]
        for y, r in zip(ys, rs):
            ax.plot([r["opt_travel"], max(r["real_travel"], r["random_travel_mean"])], [y, y], color=GRID, linewidth=2, zorder=1)
        for key, color, label in (("opt_travel", C1, "프로그램 1위"), ("real_travel", C2, "실제 선택"),
                                  ("random_travel_mean", C3, "무작위 평균")):
            ax.scatter([r[key] for r in rs], ys, s=40, color=color, edgecolor=SURFACE, linewidth=1.5, label=label, zorder=2)
        ax.set_yticks(ys, [f"{r['person']} ({r['semester']})" for r in rs])
        ax.tick_params(axis="y", length=0)
        ax.set_xlabel("주간 이동시간 (분/주)")
        ax.grid(axis="y", visible=False)
        ax.legend(loc="lower right", fontsize=8.5, ncol=3, bbox_to_anchor=(1, 1.02))
        ax.set_title("실제 시간표 (기숙사 출발)", pad=26)
        save(fig, out, "fig7_real", done)
        plt.close(fig)
    return done


# ---------------------------------------------------------------- 실행

def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--semester", default="", help="가상 묶음·분산에 쓸 학기 (기본: 지금 학기)")
    ap.add_argument("--bundles", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--real", default="", help="실제 시간표 CSV (person,semester,college,department,course,section)")
    ap.add_argument("--no-history", action="store_true", help="학기별 분산 비율(지난 편람 전부 읽기)을 건너뛴다")
    ap.add_argument("--no-stress", action="store_true", help="부하 시험(교양 4~8개, 1분 남짓)을 건너뛴다")
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("-o", "--output", default=str(OUT))
    args = ap.parse_args(argv)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    current = current_semester()
    sem = args.semester or current
    rng = random.Random(args.seed)
    t_start = time.perf_counter()

    travel = travel_matrices()
    sections, meta = load_semester(sem)
    print(f"편람 {sem}: 분반 {len(sections):,}개")

    print("1. 분반–건물 분산")
    s_rows = spread_rows(sections, meta, travel["slope"])
    s_sum = spread_summary(s_rows)
    write_csv(out / "spread_courses.csv", s_rows)
    write_csv(out / "spread_summary.csv", s_sum)
    for r in s_sum:
        print(f"  {r['group']}: {r['courses_multi_building']}/{r['courses_located']} ({pct(r['ratio'])})")
    semesters = [] if args.no_history else spread_by_semester(current)
    write_csv(out / "spread_by_semester.csv", semesters)

    print(f"2. 가상 묶음 {args.bundles}개")
    bundles = make_bundles(args.bundles, rng, sections, meta)
    b_rows, cases = [], []
    for i, b in enumerate(bundles, start=1):
        space = build_space(b.courses, rng)
        for home in HOMES:
            b_rows.append({"bundle": b.bid, "college": b.profile.college, "department": b.profile.dept, "year": b.year,
                           "courses": " | ".join(c.name for c in b.courses), **summarize(space, travel, home)})
            cases.append(js_case(group_twins(b.courses), home))
        if i % 100 == 0:
            print(f"  {i}/{len(bundles)} ({time.perf_counter() - t_start:.0f}초)")
    js = js_times(cases)
    for r, t in zip(b_rows, js or []):
        r["js_ms"] = round(t["ms"], 3)
        r["js_cost_matches"] = abs(t["cost"] - r["opt_cost"]) <= 0.051  # opt_cost 는 0.1 단위로 반올림한 값
    write_csv(out / "bundles.csv", b_rows)
    summary = bundle_summary(b_rows)
    write_csv(out / "summary.csv", summary)
    for r in summary:
        if r["home"] == "919":
            print(f"  {r['metric']}: {r['value']} {r['unit']}")

    stress = []
    if not args.no_stress:
        print("2b. 부하 시험 (수강인원 많은 교양 k개, 모든 분반)")
        stress = stress_rows(sections, meta, travel)
        write_csv(out / "stress.csv", stress)

    real = []
    if args.real:
        print("3. 실제 시간표")
        real = real_rows(Path(args.real), travel, rng, current)
        write_csv(out / "real.csv", real)

    figs = [] if args.no_figures else figures(out, s_rows, s_sum, semesters, b_rows, real)
    write_readme(out / "README.md", args, sem, summary, s_sum, semesters, stress, real, figs)
    print(f"저장: {out} ({time.perf_counter() - t_start:.0f}초)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
