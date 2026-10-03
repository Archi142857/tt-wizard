"""웹 자료 내보내기(export_web.py)와 브라우저 엔진(web/js/engine.js)이 파이썬 탐색과 같은 답을 내는지. node 가 없으면 엔진 비교는 건너뛴다."""

import json
import random
import re
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



def test_stamp_assets(tmp_path):
    """배포 때 스크립트·스타일 주소에 판(?v=)을 붙인다: 내용이 바뀌면 판도 바뀌고, 두 번 해도 같다."""
    web = tmp_path / "web"
    for name in ("index.html", "style.css", "js/app.js", "js/engine.js", "js/search-worker.js", "js/search.js"):
        (web / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "web" / name, web / name)
    v = ew.stamp_assets(web)
    html = (web / "index.html").read_text(encoding="utf-8")
    app = (web / "js" / "app.js").read_text(encoding="utf-8")
    assert f'href="style.css?v={v}"' in html and f'src="js/app.js?v={v}"' in html
    assert f'from "./engine.js?v={v}"' in app
    assert f'from "./engine.js?v={v}"' in (web / "js" / "search-worker.js").read_text(encoding="utf-8")
    # 화면이 워커·과목 검색을 붙이면 그 주소에도 판이 붙는다(붙이기 전에는 건너뛴다). 아직 안 붙였으면 붙인 셈 치고 본다
    if "./search-worker.js" not in app:
        app += '\nnew Worker(new URL("./search-worker.js", import.meta.url), { type: "module" });\n'
    if "./search.js" not in app:
        app = 'import { searchCourses } from "./search.js";\n' + app
    (web / "js" / "app.js").write_text(app, encoding="utf-8")
    v1 = ew.stamp_assets(web)
    app = (web / "js" / "app.js").read_text(encoding="utf-8")
    assert f'new URL("./search-worker.js?v={v1}"' in app and f'from "./search.js?v={v1}"' in app
    v = v1
    html = (web / "index.html").read_text(encoding="utf-8")
    assert ew.stamp_assets(web) == v and (web / "index.html").read_text(encoding="utf-8") == html
    (web / "js" / "engine.js").write_text((web / "js" / "engine.js").read_text(encoding="utf-8") + "\n// 바뀜\n", encoding="utf-8")
    v2 = ew.stamp_assets(web)
    assert v2 != v and f'src="js/app.js?v={v2}"' in (web / "index.html").read_text(encoding="utf-8")
    # 레포의 원본은 판 없이 두고, 배포할 때만 붙인다
    assert "?v=" not in (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "export_web.py --stamp" in (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")


def test_section_label_in_web():
    """화면의 분반 표기도 061(나민애) 하나다. '061분반' 모양이 다시 생기지 않게."""
    app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
    assert "function sectionLabel" in app and '"교수 미정"' in app
    assert not re.search(r"\$\{[^}]*\.no\}분반", app)


def test_search_worker_contract():
    """탐색 워커: 화면이 부를 때 쓰는 주소 모양 하나(배포 판이 붙게), 워커 파일이 엔진을 부르는지."""
    app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
    worker = (ROOT / "web" / "js" / "search-worker.js").read_text(encoding="utf-8")
    if "search-worker.js" in app:  # 화면이 워커를 붙였으면
        assert app.count('"./search-worker.js"') == 1, 'new Worker(new URL("./search-worker.js", import.meta.url), { type: "module" }) 모양으로'
    assert 'from "./engine.js"' in worker and "findConflicts" in worker and '"progress"' in worker and "countFeasible" in worker and "total" in worker


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_conflicts_and_progress():
    """겹치지 않는 조합이 없을 때 까닭인 과목(가장 작은 묶음), 진행 알림(결과는 같다), 더 찾기, 전체 조합 수."""
    run = subprocess.run(["node", str(ROOT / "tests" / "conflict_runner.mjs")], capture_output=True, text=True,
                         encoding="utf-8", check=True)
    r = json.loads(run.stdout)
    assert r["pair"] == ["A", "B"] and r["triple"] == ["A", "B", "C"] and r["ok"] == []
    assert r["feasible"] == [False, False, True]
    assert r["ticks"] >= 2 and r["ticksMonotone"] and r["lastTick"] == 1 and r["sameResult"]
    # 더 찾기: topK 를 키워 다시 찾으면 앞쪽은 그대로이고 그 뒤 순위가 이어 붙는다. 비용이 같은 조합(끝자리만 다른 것 포함)이 많은 묶음 80개
    assert r["moreOk"] == 80 and r["moreTies"] > 1000 and r["moreNoise"] > 100
    # 워커도 같다: 처음 20개(전체 수 포함) → 40개(total: false 면 다시 세지 않는다) → 전부(total 이 정확한 수)
    assert r["worker"] == {"first": True, "more": True, "all": True, "enough": True}
    # 전체 조합 수: 기본은 끝까지 센다(1만을 넘어도). limit 을 주면 그보다 많을 때 {limit, false}, 시간이 없으면 exact=false
    assert r["count"] == [{"count": 1, "exact": True}, {"count": 0, "exact": True}, {"count": 0, "exact": True}, {"count": 3, "exact": True}]
    assert r["countLimit"] == {"count": 10000, "exact": False} and r["countAll"] == {"count": 8 ** 5, "exact": True}
    assert r["countDefault"] == {"count": 8 ** 5, "exact": True} and r["countBudget"] == {"count": 0, "exact": False}
    # 하나씩 세지 않아도 하나씩 센 것과 같다: 무작위 묶음 150개(수업 여러 번·시간 없는 분반·분반 많은 과목), limit 도 같은 뜻
    assert r["randomOk"] and r["randomBig"] == 150 and r["randomLimit"]
    # 하나씩 세면 3억 개가 넘는 묶음도 바로 센다(시간이 같은 분반은 묶어 곱하고, 같은 상태는 한 번만)
    assert r["countShared"] == {"count": 5 ** 6 * 8 * 7 * 6 * 5 * 4 * 3, "exact": True}
    # 시간 제한에 걸리면 바로 멈추고 센 데까지만 준다: 다 세면 10,556,929개(하나씩 세어 확인한 값, 0.3초쯤)인 묶음을 2ms 에서 끊으면
    # 그 1/10 도 못 센다(멈추지 않고 끝까지 돌면 거의 다 센다)
    assert r["countHard"] == {"count": 10556929, "exact": True}
    assert r["countHardCut"]["exact"] is False and 0 <= r["countHardCut"]["count"] < 10556929 // 10
