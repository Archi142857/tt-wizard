"""수강 제한(®) 읽기 — 2026-2 수강편람 비고의 실제 문구로 확인한다."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from restrictions import Student, Units, can_take, split_segments  # noqa: E402

UNITS = Units({
    "화학생물공학부": "공과대학", "재료공학부": "공과대학", "기계공학부": "공과대학", "건축학과": "공과대학",
    "에너지자원공학과": "공과대학", "전기·정보공학부": "공과대학", "물리·천문학부": "자연과학대학", "화학부": "자연과학대학",
    "수리과학부": "자연과학대학", "통계학과": "자연과학대학", "생명과학부": "자연과학대학", "국어국문학과": "인문대학",
    "서양화과": "미술대학", "국악과": "음악대학", "작곡과": "음악대학", "의예과": "의과대학", "체육교육과": "사범대학",
    "수학교육과": "사범대학", "국어교육과": "사범대학", "자유전공학부": "학부대학", "언론정보학과": "사회과학대학",
})
ENG = Student("공과대학", "화학생물공학부")
MAT = Student("공과대학", "재료공학부")
MECH = Student("공과대학", "기계공학부")
ARCH = Student("공과대학", "건축학과")
EE = Student("공과대학", "전기·정보공학부")
ENERGY = Student("공과대학", "에너지자원공학과")
PHY = Student("자연과학대학", "물리·천문학부")
CHEM = Student("자연과학대학", "화학부")
MATH = Student("자연과학대학", "수리과학부")
STAT = Student("자연과학대학", "통계학과")
BIO = Student("자연과학대학", "생명과학부")
HUM = Student("인문대학", "국어국문학과")
MED = Student("의과대학", "의예과")
FREE = Student("학부대학", "자유전공학부")


def ok(remark, student, section_dept="", year=None):
    if year is not None:
        student = Student(student.college, student.dept, year)
    return can_take(remark, section_dept, student, UNITS)


def test_open_and_special():
    assert ok("", HUM) and ok("수강신청 4일차까지 1학년만", HUM)  # ®가 없으면 누구나
    assert not ok("<외국인 유학생반>: '글로벌인재특별전형'의 1유형으로 입학한 학생과 교환 학생만 수강 가능", HUM)
    assert not ok("ⓔ외국인 학생(영어강좌) / 선착순 1일차까지 1학년만 수강신청 가능", HUM)
    assert not ok("®", HUM) and not ok("®6학기 이상 이수자 수강 가능", HUM)  # 못 읽으면 못 듣는다


def test_split_keeps_dates_and_parentheses():
    assert split_segments("8/4~8/7 공대 소속 / 수강신청 변경기간") == ["8/4~8/7 공대 소속 ", " 수강신청 변경기간"]
    assert len(split_segments("전기∙정보공학부 주전공 혹은 제2전공(복수/부전공)만")) == 1


@pytest.mark.parametrize("remark, yes, no", [
    ("®물리천문학부 제외 (정원 외 신청은 없습니다. 관련사항 물리학부 게시판 공지사항을 확인하여 주세요.)", [ENG, HUM], [PHY]),
    ("®전체단과대(의예과 제외)(정원외신청은  https://chem.snu.ac.kr/ 확인 후 수강사이트)", [ENG, HUM], [MED]),
    ("®의예과(정원외신청은  https://chem.snu.ac.kr/ 확인 후 수강사이트)", [MED], [ENG]),
    ("®공과대학 / 선착순 1일차까지 1학년만 수강신청 가능", [ENG, MECH], [HUM, PHY]),
    ("®자연대, 공대(정원외신청은  https://chem.snu.ac.kr/ 확인 후 수강사이트)", [ENG, CHEM], [HUM]),
    ("®경영대, 농생대, 사범대, 사회과학대, 생활과학대, 인문대, 학부대학(자유전공+광역) / 선착순 1일차까지", [HUM, FREE], [ENG]),
    ("®공대_재료공학부(정원외신청은  https://chem.snu.ac.kr/ 확인 후 수강사이트)", [MAT], [ENG, MECH]),
    ("®공대_화학생물공학부, 재료공학부(정원외신청은  https://chem.snu.ac.kr/ 확인 후 수강사이트)", [ENG, MAT], [MECH]),
    ("®자연대(화학부 외), 공대(화생공, 재료공 외), 자전, 사범, 농생대, 첨단융합학부, 학부대학(정원외신청은  https://chem.snu.ac.kr/)",
     [MECH, PHY, FREE], [ENG, MAT, CHEM, HUM]),
    ("®수강신청 4일차까지 자연대 수리과학부, 통계학과 1학년 학생만 수강신청 가능하며, 수강신청 5일차부터 자연대 수리과학부, "
     "통계학과 전체 학년이 수강신청 가능하고", [MATH, STAT], [PHY, ENG]),
    ("®수강신청기간 동안 공과대학 건축학과 1학년만 수강신청 가능하며, 수강신청 변경기간부터 해당학과 전학년 수강신청 가능/ "
     "[수학 1] 과 [수학연습 1] 담당 교수가 일치하지 않아도 됨", [ARCH], [ENG]),
    ("®에너지자원공학과 학생만 수강 가능(본 수강신청 2학년, 수강신청변경기간 전체학년)", [ENERGY], [ENG, HUM]),
    ("®과제신청 및 면담신청서 제출은 전기∙정보공학부 홈페이지(http://ece.snu.ac.kr)에 별도 공지 하며, 전기∙정보공학부 학사 "
     "주전공 혹은 제2전공(복수/부전공)만 수강신청 가능", [EE], [ENG]),
    ("®'* 공과대학, 자연과학대학, 농업생명과학대학, 수의과대학, 간호대학, 약학대학, 의과대학, 의학대학원, 치의학대학원, "
     "첨단융합학부, 사범대학(수학교육과, 지구과학교육과, 물리교육과, 화학교육과, 생물교육과) 위 11개 단과대학 이외에는 수강신청 불가",
     [ENG, PHY, Student("사범대학", "수학교육과")], [HUM, Student("사범대학", "국어교육과")]),
])
def test_allow_lists(remark, yes, no):
    for s in yes:
        assert ok(remark, s), (remark, s)
    for s in no:
        assert not ok(remark, s), (remark, s)


@pytest.mark.parametrize("remark, yes, no", [
    ("®수리과학부 주전공 및 제2전공 수강불허(수리과학부 진입예정자 수강시 전공 불인정)", [ENG, HUM, PHY], [MATH]),
    ("®미대생 수강불허", [HUM], [Student("미술대학", "서양화과")]),
    ("®음대생 수강 불허(국악과만 수강 가능)", [HUM, Student("음악대학", "국악과")], [Student("음악대학", "작곡과")]),
    ("®언론정보학과 주전공 및 제2전공생 수강 불허", [HUM], [Student("사회과학대학", "언론정보학과")]),
    ("®영어 강의 / 통계학과 소속 학생 수강신청 불가 / 본 교과목 수강신청 학생은 통계학실험 017 강좌 수강신청 권장", [HUM], [STAT]),
    ("®(R 활용 강좌) 통계학 012(영어강의) 수강 학생 수강신청 권고(단, 실습은 한국어로 진행) / 통계학과 소속 학생 수강신청 불가",
     [HUM, CHEM], [STAT]),
    ("®생명과학부 주전공 및 2전공자(자유전공학부 주전공 포함) 수강 불가 / 수강신청 1~4일차까지는 생명과학부 주전공생 및 "
     "제2전공 제외한 1학년만 수강신청 가능", [HUM, CHEM], [BIO]),
    ("®체육교육과 외 수강 불허", [Student("사범대학", "체육교육과")], [HUM]),
    ("®사범대학 학생 외 수강 불허", [Student("사범대학", "국어교육과")], [HUM]),
])
def test_bars_and_only(remark, yes, no):
    for s in yes:
        assert ok(remark, s), (remark, s)
    for s in no:
        assert not ok(remark, s), (remark, s)


def test_registration_phases_use_first_allocation():
    """본 수강신청 배정(첫 조각)으로 정한다. 변경기간에 '모든 학생' 으로 넓혀도 보지 않는다."""
    stat = ("®8/4~8/7 통계학과를 제외한 자연대 소속 1학년만 수강신청 가능 / 8/10~8/11 통계학과를 제외한 자연대 소속 "
            "전체 학년 수강신청 가능 / 수강신청 변경기간에는 통계학과 학생을 제외한 모든 학생 수강신청 가능")
    assert ok(stat, CHEM) and ok(stat, CHEM, year=3)  # '전체 학년' 으로 넓혔으니 학년은 안 따진다
    assert not ok(stat, STAT) and not ok(stat, HUM) and not ok(stat, ENG)
    arch = "®1단계 : 건축학과 1학년만 수강신청 가능 / 2~3단계 : 건축학과 1학년 및 건축학과 제2전공 학생 수강신청 가능"
    assert ok(arch, ARCH, year=1) and not ok(arch, ARCH, year=2) and ok(arch, ARCH) and not ok(arch, ENG)


def test_years():
    mat = "®재료공학부 주전공, 복수전공, 부전공 3, 4학년만 수강신청 가능, 교환학생 수강 불허"
    assert ok(mat, MAT, year=3) and not ok(mat, MAT, year=2) and ok(mat, MAT) and not ok(mat, ENG)
    chem1 = "®전체단과대(화학부 1학년 제외)(정원외신청은  https://chem.snu.ac.kr/ 확인 후 수강사이트)"
    assert not ok(chem1, CHEM, year=1) and ok(chem1, CHEM, year=2) and ok(chem1, ENG)
    assert ok("®화학부 1학년(정원외신청은  https://chem.snu.ac.kr/)", CHEM, year=1)
    assert not ok("®화학부 1학년(정원외신청은  https://chem.snu.ac.kr/)", CHEM, year=2)
    upper = "®공대:화생공, 재료공 2학년 이상(정원외신청은  https://chem.snu.ac.kr/ 확인 후 수강사이트)"
    assert ok(upper, ENG, year=2) and not ok(upper, ENG, year=1) and not ok(upper, MECH)
    fresh = "®※ 1학년만 수강가능 [[창의와 도전] 웹툰과 서사] - 일정 및 장소, 수강대상 등은 강의계획서 참고"
    assert ok(fresh, HUM, year=1) and not ok(fresh, HUM, year=2) and ok(fresh, HUM)


def test_other_department_and_major_rules():
    assert ok("®타과생 수강금지", ENG, "화학생물공학부") and not ok("®타과생 수강금지", CHEM, "화학생물공학부")
    assert ok("®타과생은 5~6일차에 수강신청 가능", HUM, "건축학과")
    assert not ok("®건축학과 제2전공 학생은 5~6일차에 수강신청 가능, 타과생 정원외신청", ENG, "건축학과")
    assert ok("®주전공생 대상 강좌", CHEM, "화학부") and not ok("®주전공생 대상 강좌", HUM, "화학부")
    assert not ok("®주전공생 수강 불허", CHEM, "화학부") and ok("®주전공생 수강 불허", HUM, "화학부")
    mech = ("®기계공학부, 기계항공공학부(기계/기계항공) 주전공만 수강 가능 (자유, 다전공 포함) 1~4일차: 해당전공 3학년 초수강생 "
            "5~6일차: 해당전공 초수강생 *재수강 불가, 타과생 수강불가")
    assert ok(mech, MECH, "기계공학부") and not ok(mech, ENG, "기계공학부")
    assert not ok("®수강신청4일차까지  [미적분학연습 2] 대상학부 1학년 학생만 수강신청 가능하며, 수강신청 5일차부터  "
                  "[미적분학연습 2] 대상 학부 전체학년 수강신청 가능", HUM)  # 대상 학부가 따로 있다


def test_second_review_cases():
    """다시 검토에서 나온 문구 (9/29)."""
    phy2 = "®자연대(물리천문제외) / 선착순 1일차까지 1학년만 수강신청 가능"
    assert ok(phy2, CHEM) and not ok(phy2, PHY) and not ok(phy2, HUM) and not ok(phy2, ENG)
    geo = "®자연대(지구환경과학부 제외), 농생대, 공대, 학부대학 수강가능, 지구시스템과학실험(F36.103L)동시수강"
    assert ok(geo, CHEM) and ok(geo, ENG) and not ok(geo, HUM)
    econ = "®경제학부홈페이지참조] 타과생 수강불허 (예외없음), 자전 경제학주전공자는 201강좌 수강신청 가능"
    ECON = Student("사회과학대학", "경제학부")
    assert ok(econ, ECON, "경제학부") and not ok(econ, FREE, "경제학부") and not ok(econ, HUM, "경제학부")
    arch = ("®수강신청기간 동안 공과대학 건축학과 1학년만 수강신청 가능하며, 수강신청 변경기간부터 해당학과 전학년 수강신청 가능/ "
            "[수학 1] 과 [수학연습 1] 담당 교수가 일치하지 않아도 됨")
    assert ok(arch, ARCH, year=1) and not ok(arch, ARCH, year=2)  # 변경기간에 넓히는 것은 보지 않는다
    energy = "®에너지자원공학과 학생만 수강 가능(본 수강신청 2학년, 수강신청변경기간 전체학년)"
    assert ok(energy, ENERGY, year=2) and not ok(energy, ENERGY, year=3)
    biz = "®수강신청 4일차까지 경영대 1학년 학생만 수강신청 가능, 수강신청 5일차부터 경영대 전 학년 수강신청 가능"
    assert ok(biz, Student("경영대학", "경영학과"), year=3)  # 본 기간 안(5일차)에 넓힌다
    ee = ("®(수강신청 1~4일) 전기·정보공학부 학사 주전공, 제2전공(복수전공,부전공), 자유전공학부(전기·정보공학부 주전공), "
          "연합전공 인공지능반도체공학 초수강생만 신청 가능 / (수강신청 5~6일) 전기·정보공학부 학사 주전공")
    assert ok(ee, EE) and not ok(ee, FREE) and not ok(ee, ENG)
    art = "®[서양화과 주전공 4학년, 복수전공 진입생, 자유전공학부 학생 중 서양화과 진입생] 외 수강 불허"
    assert ok(art, Student("미술대학", "서양화과")) and not ok(art, FREE) and not ok(art, HUM)

