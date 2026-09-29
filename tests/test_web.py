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
