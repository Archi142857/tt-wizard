"""과목 검색(web/js/search.js): 줄임말·초성 섞기·치는 중인 글자·한영 자판·특별 낱말과 줄 세우기. node 가 없으면 건너뛴다.

작은 가짜 과목 목록으로 순서를 확인하고, 실제 자료(data/lectures.json)로는 빠르기와 규칙(그리고·정렬·강조 범위)만 본다.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import export_web as ew  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")


def course(cid, name, dept, credit=3, cls="전선", program="학사", secs=None):
    """courses.json 의 과목 한 줄. secs: [(분반, 교수, [(요일, 시작, 끝, 건물, 강의실)])]"""
    secs = secs or [("001", "", [(0, 600, 690, "", "")])]
    return [cid, name, dept, credit, cls, program, [[no, prof, "", [list(m) for m in ms]] for no, prof, ms in secs]]


COURSES = [
    course("F11.101", "대학 글쓰기 1", "국어국문학과", 2, "교양", secs=[("001", "나민애", [(0, 600, 690, "1", "101")]), ("002", "김철수", [(1, 600, 690, "1", "102")])]),
    course("F11.201", "대학 글쓰기 2: 인문학글쓰기", "학부대학", 2, "교양", secs=[("001", "이영희", [(2, 600, 690, "14", "201")])]),
    course("F21.201", "대학영어 2: 글쓰기", "영어영문학과", 3, "교양", secs=[("001", "Brandon Ives", [(0, 780, 870, "2", "105")])]),
    course("E52.102", "글쓰기 세미나", "학부대학", 1, "교양"),
    course("C10.101", "고대그리스.로마문학의 세계", "협동과정  서양고전학전공", 3, "교양"),
    course("F37.202", "컴퓨터의 개념 및 실습", "산업공학과", 3, "교양"),
    course("4190.308", "컴퓨터구조", "컴퓨터공학부", 3, "전필"),
    course("M1522.000900", "자료구조", "컴퓨터공학부", 3, "전필", secs=[("001", "박교수", [(0, 840, 915, "301", "118")])]),
    course("M3639.001700", "자료구조와 알고리즘", "첨단융합학부"),
    course("M2175.011200", "특수환자군 약료학", "약학대학", 2),
    course("4013.311", "구조동역학", "건축학과"),
    course("M9999.000100", "구강조직학", "치의학과"),
    course("881.007", "선형대수학", "수리과학부"),
    course("430.216", "전기시스템선형대수", "전기·정보공학부"),
    course("F31.201", "공학수학 1", "학부대학", 3, "교양"),
    course("F31.202", "공학수학 2", "학부대학", 3, "교양", secs=[("001", "정교수", [(1, 840, 915, "301", "118")])]),
    course("F31.104L", "수학연습 1", "수리과학부", 1, "교양"),
    course("3343.702", "화학특수연구 2", "화학부", 3, "전선", "석박사통합"),
    course("F33.105", "물리학", "물리·천문학부", 3, "교양"),
    course("F33.105L", "물리학실험", "물리·천문학부", 1, "교양"),
    course("M3500.000200", "(공유)AI입문", "혁신공유학부"),
    course("M3502.009200", "(공유)대규모언어모델 활용", "혁신공유학부"),
    course("715.603", "그래프이론", "수학교육과"),
    course("M1314.005800", "AI 금융경제", "경제학부", 2),
    course("4190.307", "운영체제", "컴퓨터공학부"),
    course("E11.146", "심리학개론", "심리학과", 3, "교양"),
    course("132.502", "인지과학방법론", "협동과정  인지과학전공", 3, "전선", "석사"),
    course("F27.302", "고급 한국어 Ⅱ", "국어국문학과", 3, "교양"),
    course("3341.636", "편미분방정식론 2", "수리과학부", 3, "전선", "박사"),
    course("881.003", "미분방정식", "수리과학부"),
    course("E43.101", "건강과 삶", "체육교육과", 1, "교양", secs=[("001", "최교수", [(4, 540, 630, "43-1", "101")])]),
    course("E43.102", "골프초급", "체육교육과", 1, "교양", secs=[("001", "최교수", [(4, 540, 630, "71", "101")])]),
    # 특별 낱말이 과목명에 든 과목: '교양' 이 낱말 머리에 있는 전선 과목, '전공' 이 낱말 안쪽에만 있는 교양 과목
    course("105.654", "현대독문학연습 (교양소설)", "독어독문학과", 3, "전선", "석박사통합"),
    course("E12.104", "한국근대소설의 이해", "국어국문학과", 3, "교양"),
    course("C30.105", "유전공학의 이해", "생명과학부", 2, "교양"),
]


def run(tmp_path, courses, queries=(), typing=(), top=10):
    cpath, qpath = tmp_path / "courses.json", tmp_path / "cases.json"
    cpath.write_text(json.dumps({"courses": courses}, ensure_ascii=False), encoding="utf-8")
    qpath.write_text(json.dumps({"queries": list(queries), "typing": list(typing), "top": top}, ensure_ascii=False), encoding="utf-8")
    res = subprocess.run(["node", str(ROOT / "tests" / "search_runner.mjs"), str(cpath), str(qpath)],
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.fixture(scope="module")
def found(tmp_path_factory):
    queries = ["대글", "ㄷㅎ글쓰기", "대ㄱ쓰기", "글쓱", "그", "eogkr rmfTmrl", "컴공과", "글쓰기 나민애", "ㄴㅁㅇ", "컴개실",
               "자구", "선대", "수연", "구조", "교양", "전공", "대학원", "학부", "3학점", "301동", "301-118", "301-1", "43-1",
               "M1522.000900", "m1522000900", "1522", "M1522.000900 001", "일물", "공수1", "AI", "고급 한국어 2", "인지과", "미방",
               "운체", "ㅇㅇㅊㅈ", "", "   ", "··", "대학 ", "대하", "글쓰기 나", "컴공 자",
               "교양 3학점", "3학점 교양", "교양 소설", "소설 교양", "전공 3학점", "·· 교양"]
    out = run(tmp_path_factory.mktemp("search"), COURSES, queries, top=40)
    return {r["q"]: r for r in out["results"]}, out


def ids(r):
    return [h["id"] for h in r["hits"]]


def test_abbreviation(found):
    by, _ = found
    assert ids(by["대글"])[:2] == ["F11.101", "F11.201"] and by["대글"]["hits"][0]["kind"] == "initials"
    assert ids(by["대글"]).index("C10.101") > ids(by["대글"]).index("F21.201")  # 고대그리스(치는 중 '글' → 그+ㄹ)는 줄임말 뒤
    hit = by["컴개실"]["hits"][0]
    assert hit["id"] == "F37.202" and hit["marks"]["name"] == [[0, 1], [5, 6], [10, 11]]
    assert ids(by["자구"])[:2] == ["M1522.000900", "M3639.001700"]
    assert ids(by["자구"]).index("M2175.011200") > 1  # 특수환자군(치는 중인 '구' → 군)은 뒤
    assert ids(by["선대"]) == ["881.007", "430.216"]
    assert ids(by["미방"]) == ["881.003", "3341.636"]
    assert ids(by["운체"])[0] == "4190.307"
    assert ids(by["공수1"]) == ["F31.201"]


def test_abbreviation_beats_inside_only_when_no_word_matches(found):
    by, _ = found
    # '수연': 어느 과목명에도 낱말 머리로 이어진 '수연' 이 없다 → 줄임말로 보고 수학연습이 화학특수연구보다 앞
    assert ids(by["수연"])[:2] == ["F31.104L", "3343.702"]
    # '구조': 구조동역학이 있으니 낱말 → 안(자료구조) → 줄임(구강조직학) 그대로
    got = ids(by["구조"])
    assert got[0] == "4013.311" and got.index("M1522.000900") < got.index("M9999.000100")


def test_chosung_and_typing(found):
    by, _ = found
    top = by["ㄷㅎ글쓰기"]["hits"][0]
    assert top["id"] in ("F11.101", "F11.201") and top["kind"] == "name" and top["marks"]["name"] == [[0, 6]]
    assert ids(by["대ㄱ쓰기"])[:2] == ["F11.101", "F11.201"]
    assert ids(by["ㅇㅇㅊㅈ"]) == ["4190.307"]
    # '글쓱' = 글쓰 + 다음 글자 첫소리 ㄱ: 글쓰기가 든 과목 모두, 과목명 처음인 글쓰기 세미나가 먼저
    assert ids(by["글쓱"])[0] == "E52.102" and {"F11.101", "F11.201", "F21.201"} <= set(ids(by["글쓱"]))
    assert by["글쓱"]["hits"][0]["marks"]["name"] == [[0, 3]]
    # '그': 그대로 맞는 그래프이론이 치는 중으로 맞는 글쓰기 세미나(글)보다 앞
    assert ids(by["그"]).index("715.603") < ids(by["그"]).index("E52.102")
    # 끝에 띄어쓰기면 다 친 낱말: '대학 ' 은 '대하' 처럼 학까지 맞추지 않는다
    assert "F11.101" in ids(by["대하"]) and "F11.101" in ids(by["대학 "])
    assert by["대하"]["hits"][0]["score"] > 1  # 치는 중으로 맞은 것은 뒤로(처음 1.5)


def test_qwerty_dept_prof(found):
    by, _ = found
    assert ids(by["eogkr rmfTmrl"])[:2] == ["F11.101", "F11.201"]
    got = by["컴공과"]
    assert set(ids(got)) == {"4190.308", "M1522.000900", "4190.307"} and all(h["kind"] == "dept" for h in got["hits"])
    assert got["hits"][0]["marks"]["dept"] == [[0, 1], [3, 4]]
    assert "132.502" in ids(by["인지과"])  # 협동과정 인지과학전공: 낱말 머리부터
    hit = by["글쓰기 나민애"]["hits"]
    assert [h["id"] for h in hit] == ["F11.101"] and hit[0]["marks"]["prof"] == {"name": "나민애", "ranges": [[0, 3]]}
    assert any(h["id"] == "F11.101" and h["kind"] == "prof" for h in by["ㄴㅁㅇ"]["hits"])
    # 여러 낱말이면 한 글자도 교수 이름·학과 앞부분: 치는 동안 결과가 사라졌다 다시 나오지 않게
    assert "F11.101" in ids(by["글쓰기 나"]) and ids(by["컴공 자"])[0] == "M1522.000900"


def test_special_words(found):
    by, _ = found
    cls = {c[0]: c[4] for c in COURSES}
    # 과목명 낱말 머리에 그 말이 있는 과목도 맞는다('(교양소설)'). 안쪽에만 있는 것('유전공학' 의 전공)은 아니다
    assert set(ids(by["교양"])) == {k for k, v in cls.items() if v == "교양"} | {"105.654"}
    assert set(ids(by["전공"])) == {k for k, v in cls.items() if v in ("전선", "전필")}
    grad = {c[0] for c in COURSES if c[5] in ("석사", "박사", "석박사통합")}
    assert set(ids(by["대학원"])) == grad and not set(ids(by["학부"])) & grad
    assert set(ids(by["3학점"])) == {c[0] for c in COURSES if c[3] == 3}
    assert set(ids(by["301동"])) == set(ids(by["301-118"])) == set(ids(by["301-1"])) == {"M1522.000900", "F31.202"}
    assert ids(by["43-1"]) == ["E43.101"]  # 43-1동. 교과목번호 E43.1xx 는 아니다


def test_special_words_filter_first(found):
    """특별 낱말을 다른 낱말과 함께 치면 거르는 말이 먼저다: '교양 3학점' 은 교양이면서 3학점인 과목이 앞이고,
    과목명에만 '교양' 이 있는 전선 과목은 맨 뒤. 그 낱말만 쳤을 때는 과목명에 그 말이 있는 과목이 앞."""
    by, _ = found
    want = [c[0] for c in COURSES if c[4] == "교양" and c[3] == 3]
    for q in ("교양 3학점", "3학점 교양"):
        got = by[q]
        assert set(ids(got)[:-1]) == set(want) and ids(got)[-1] == "105.654", q
        assert all(h["kind"] == "special" and not h["marks"] for h in got["hits"][:-1])
        assert got["scores"][-1] > got["scores"][0] == pytest.approx(8.01, abs=1e-6)
    assert ids(by["교양"])[0] == "105.654" and by["교양"]["hits"][0]["marks"]["name"] == [[9, 11]]  # 한 낱말: 과목명에 있는 과목이 앞
    assert by["교양"]["scores"][0] < 2 and by["교양"]["scores"][1] == 8
    assert ids(by["·· 교양"]) == ids(by["교양"])  # 글자가 없는 낱말은 세지 않는다
    assert ids(by["교양 소설"])[0] == "105.654"   # 띄어 쓴 말 전체가 과목명에 이어져 있으면 그것이 먼저(교양소설)
    assert ids(by["소설 교양"]) == ["E12.104", "105.654"]
    got = by["전공 3학점"]
    assert set(ids(got)) == {c[0] for c in COURSES if c[4] in ("전선", "전필") and c[3] == 3}
    assert len(set(got["scores"])) == 1  # 거른 과목끼리는 같은 점수(가나다순)


def test_course_number_and_misc(found):
    by, out = found
    hit = by["M1522.000900"]["hits"]
    assert [h["id"] for h in hit] == ["M1522.000900"] and hit[0]["kind"] == "id" and hit[0]["marks"]["id"] == [[0, 12]]
    assert ids(by["m1522000900"]) == ["M1522.000900"]
    assert ids(by["1522"]) == ["M1522.000900"] and by["1522"]["hits"][0]["marks"]["id"] == [[1, 5]]
    assert ids(by["M1522.000900 001"]) == ["M1522.000900"]
    assert ids(by["일물"])[:2] == ["F33.105", "F33.105L"]
    got = by["AI"]["hits"]
    assert {h["id"] for h in got[:2]} == {"M3500.000200", "M1314.005800"}
    assert next(h for h in got if h["id"] == "M3500.000200")["marks"]["name"] == [[4, 6]]
    assert ids(by["고급 한국어 2"]) == ["F27.302"] and by["고급 한국어 2"]["hits"][0]["marks"]["name"] == [[0, 8]]
    assert by[""]["count"] == by["   "]["count"] == by["··"]["count"] == 0
    for r in by.values():
        assert r["scores"] == sorted(r["scores"])
    assert out["extra"]["splitMarks"] == [{"text": "대", "mark": True}, {"text": "학 ", "mark": False},
                                          {"text": "글", "mark": True}, {"text": "쓰기", "mark": False}]
    assert out["extra"]["normKey"] == "공유ai입문2"
    assert out["extra"]["qwerty"] == ["글쓰기", "알고리즘", "까", "왜", "값", "값이", "갑사", None]


def test_real_data_speed_and_rules(tmp_path):
    """실제 과목(data/lectures.json): 한 글자 칠 때마다 검색해도 빠른가, 여러 낱말은 각 낱말을 모두 만족하나, 강조 범위가 글자 안인가."""
    lectures = ROOT / "data" / "lectures.json"
    if not lectures.exists():
        pytest.skip("data/lectures.json 없음")
    courses = ew.export_courses(lectures)["courses"]
    multi = ["대학 글쓰기", "컴공 자구", "글쓰기 교양", "물리학 2", "AI 3학점"]
    words = sorted({w + " " for q in multi for w in q.split()[:-1]} | {q.split()[-1] for q in multi})
    typing = ["대학 글쓰기", "컴퓨터의 개념 및 실습", "자료구조", "선형대수학", "글쓰기 나민애", "수학연습", "M1522.000900", "301동", "eogkr rmfTmrl"]
    out = run(tmp_path, courses, multi + words + ["ㄱ", "대", "교양", "그"], typing, top=50)
    by = {r["q"]: r for r in out["results"]}
    for q in multi:  # 그리고: 여러 낱말 결과는 낱말마다의 결과 안에 있다
        parts = q.split()
        each = [set(by[w + " "]["ids"]) for w in parts[:-1]] + [set(by[parts[-1]]["ids"])]
        assert set(by[q]["ids"]) <= set.intersection(*each), q
    names = {c[0]: c for c in courses}
    for r in out["results"]:
        assert r["scores"] == sorted(r["scores"]), r["q"]
        for h in r["hits"]:
            c = names[h["id"]]
            for key, text in (("name", c[1]), ("id", c[0]), ("dept", c[2])):
                for a, b in h["marks"].get(key, []):
                    assert 0 <= a < b <= len(text), (r["q"], key, text)
            if "prof" in h["marks"]:
                assert h["marks"]["prof"]["name"] in {s[1] for s in c[6]}
    bench = out["bench"]
    assert bench["keys"] > 100
    # 한 글자마다 다시 찾는다(app.js). 이 PC·CI 에서 평균 몇 ms — 크게 느려지면(알고리즘 실수) 잡는다
    assert bench["avgMs"] < 40 and bench["maxMs"] < 400 and bench["indexMs"] < 3000, bench
