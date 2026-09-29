"""웹 자료 내보내기(export_web.py)와 브라우저 엔진(web/js/engine.js)이 파이썬 탐색과 같은 답을 내는지. node 가 없으면 엔진 비교는 건너뛴다."""

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ttwizard.models import Course, Meeting, Section
from ttwizard.search import search
from ttwizard.travel import Building, TravelMatrix

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import export_web as ew  # noqa: E402

SAMPLE = ROOT / "data" / "sample"


def _export(tmp_path):
    out = tmp_path / "web"
    assert ew.main(["--data", str(SAMPLE), "-o", str(out)]) == 0
    return json.loads((out / "courses.json").read_text(encoding="utf-8")), json.loads((out / "campus.json").read_text(encoding="utf-8")), out


def _python_side(courses_json, campus, mode="flat"):
    courses = {}
    for cid, name, _dept, _credit, _cls, _prog, secs in courses_json["courses"]:
        courses[cid] = Course(cid, name, [Section(cid, no, name, tuple(Meeting(*m) for m in ms), instructor=ins)
                                          for no, ins, _st, ms in secs])
    dense = campus[mode] or campus["flat"]
    ids = campus["ids"]
    table = {(a, b): dense[i][j] for i, a in enumerate(ids) for j, b in enumerate(ids)
             if i != j and dense[i][j] is not None}
    buildings = {b: Building(b, v[0], v[1], v[2]) for b, v in campus["buildings"].items()}
    return courses, TravelMatrix(buildings=buildings, table=table)


def test_room_no():
    assert ew.room_no("38-B105(무선랜제공)") == "B105"
    assert ew.room_no("220-1-201") == "201" and ew.room_no("083-302") == "302" and ew.room_no("") == ""


def test_export_web(tmp_path):
    courses, campus, out = _export(tmp_path)
    assert courses["courses"] and all(len(c) == 7 for c in courses["courses"])
    assert campus["ids"] and len(campus["flat"]) == len(campus["ids"])
    assert all(campus["flat"][i][i] == 0 for i in range(len(campus["ids"])))
    assert (out / "routes.json").exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_web_engine_matches_python(tmp_path):
    courses_json, campus, out = _export(tmp_path)
    courses, travel = _python_side(courses_json, campus)
    rng = random.Random(7)
    ids = [c for c in courses if len(courses[c].sections) >= 1]
    cases = [{"ids": rng.sample(ids, min(len(ids), rng.randint(2, 4))), "home": "919", "mode": "flat", "topK": 5}
             for _ in range(12)]
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    run = subprocess.run(["node", str(ROOT / "tests" / "web_runner.mjs"), str(out / "courses.json"),
                          str(out / "campus.json"), str(tmp_path / "cases.json")],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    js = json.loads(run.stdout)
    for case, got in zip(cases, js):
        res = search([courses[i] for i in case["ids"]], travel, case["home"], top_k=5)
        assert got == pytest.approx([e.cost for e in res.ranked], abs=1e-5), case


def test_export_semesters(tmp_path):
    """학기 선택: 지난 학기(data/history/<학기>.json)를 web/data/semesters/ 로, 목록은 최신 학기부터."""
    data = tmp_path / "data"
    shutil.copytree(SAMPLE, data)
    (data / "sync_state.json").write_text(json.dumps({"semester": "2027-1", "lectures_semester": "2026-2"}), encoding="utf-8")
    hist = data / "history"
    hist.mkdir()
    for label in ("2025-2", "2026-1"):
        payload = ew.export_courses(SAMPLE / "lectures.json")
        payload["meta"] = {"semester": label, "updated": ""}
        (hist / f"{label}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (hist / "2026-2.json").write_text("{}", encoding="utf-8")  # 지금 학기는 lectures.json 을 쓴다
    (hist / "notes.json").write_text("{}", encoding="utf-8")  # 학기 이름이 아니면 무시
    out = tmp_path / "web"
    assert ew.main(["--data", str(data), "-o", str(out)]) == 0
    idx = json.loads((out / "semesters.json").read_text(encoding="utf-8"))
    # 새 학기(2027-1)를 감지했어도 아직 받기 전이면 lectures.json 은 2026-2 다
    assert idx == {"current": "2026-2", "list": [["2026-2", "courses.json"], ["2026-1", "semesters/2026-1.json"],
                                                  ["2025-2", "semesters/2025-2.json"]]}
    assert json.loads((out / "courses.json").read_text(encoding="utf-8"))["meta"]["semester"] == "2026-2"
    assert json.loads((out / "semesters" / "2025-2.json").read_text(encoding="utf-8"))["meta"]["semester"] == "2025-2"
    assert sorted(ew.semester_key(x) for x in ("2026-W", "2026-1", "2026-S", "2026-2")) == [(2026, 0), (2026, 1), (2026, 2), (2026, 3)]

