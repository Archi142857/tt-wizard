"""수강편람 비고의 수강 제한(®) 읽기: 이 학생이 이 분반을 신청할 수 있나.

비교 실험(scripts/experiments.py)이 학생마다 고를 수 있는 분반을 정할 때 쓴다. 규칙은 실제 문구로
tests/test_restrictions.py 에서 확인한다. 비고는 사람이 쓴 문장이라 규칙으로 다 읽을 수는 없다.

1. 특정 학생만 받는 분반(외국인 유학생반, 글로벌 인재반, 외국인 학생(영어강좌), 교환 학생만)은 뺀다. ®가 없으면 누구나
2. ® 뒤 문구에서 안내 괄호(정원 외 신청·주소·홈페이지 안내)를 지우고 '/' 로 나눈다(괄호 안, 날짜 8/4 같은 '/' 는 두고).
   단과대·학과 이름, '모든 학생', '전체단과대', '타과생', '주전공', 'N학년만' 이 처음 나오는 조각이
   본 수강신청 기간의 배정이라 보고 그 조각으로 정한다(뒤의 수강신청 변경기간 안내는 보지 않는다)
3. 이름마다 뒤에 처음 오는 말로 뜻을 정한다: '제외' → 빼기, '불허·불가·금지·제한' → 막기, 그 밖 → 받기.
   '(… 외)', '(… 제외)' 괄호 안의 이름은 빼기. 'X 외 수강 불허', 'X 이외에는 … 불가' 는 X 만 받기
4. 학과 이름이 단과대 이름보다 앞선다: 받는 학과가 적힌 단과대는 그 학과만('공대_재료공학부', '자연대 수리과학부, 통계학과').
   막힌 단과대 안에서 따로 받는 학과는 예외다('음대생 수강 불허(국악과만 수강 가능)')
5. 받기 목록이 있으면 거기 들어야, 없으면(막기·빼기만) 거기 안 걸리면 들을 수 있다. '모든 학생', '전체단과대' 는 누구나
6. '타과생' 이 막히면(금지·불허·불가·제한·정원외) 개설학과 학생만, '타과생 … 가능' 은 누구나.
   이름 없는 '주전공' 은 개설학과 학생만('주전공생 수강 불허' 는 개설학과 학생만 못 듣는다)
7. 'N학년만', 'N학년 이상', '(학과) N학년' 은 학년을 알 때만 따지고, 문구 어디엔가 '전 학년·전체 학년' 으로
   넓히는 말이 있으면 따지지 않는다
8. 정할 조각이 없으면(® 만 있는 등) 못 듣는 것으로 본다(보수적)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

COLLEGE_ALIASES = {
    "인문대학": ("인문대학", "인문대"),
    "사회과학대학": ("사회과학대학", "사회과학대", "사회대"),
    "자연과학대학": ("자연과학대학", "자연과학대", "자연대"),
    "간호대학": ("간호대학", "간호대"),
    "경영대학": ("경영대학", "경영대"),
    "공과대학": ("공과대학", "공과대", "공대"),
    "농업생명과학대학": ("농업생명과학대학", "농업생명과학대", "농생대"),
    "미술대학": ("미술대학", "미술대", "미대"),
    "사범대학": ("사범대학", "사범대", "사범"),
    "생활과학대학": ("생활과학대학", "생활과학대", "생활대"),
    "수의과대학": ("수의과대학", "수의대"),
    "약학대학": ("약학대학", "약대"),
    "음악대학": ("음악대학", "음악대", "음대"),
    "의과대학": ("의과대학", "의대"),
    "치의학대학원": ("치의학대학원", "치과대학", "치의대"),
    "학부대학": ("학부대학",),
    "첨단융합학부": ("첨단융합학부",),
}
# 비고에 줄여 쓰는 학과 이름 (정식 이름은 수강편람의 개설학과에서 모은다)
DEPT_ALIASES = {
    "화생공": "화학생물공학부", "재료공": "재료공학부", "물리천문": "물리천문학부", "전기정보": "전기정보공학부",
    "자유전공": "자유전공학부", "자전": "자유전공학부", "경제학주": "경제학부",
}
_DOTS = re.compile(r"[\s·∙•・‧ㆍ]")
_SPECIAL = re.compile(r"유학생반|글로벌\s*인재반|외국인\s*학생\s*\(|교환\s*학생만")
_NOTE = re.compile(r"\([^()]*(?:정원|http|홈페이지|게시판|공지|확인|eTL)[^()]*\)|https?://\S+")
_CUE = re.compile(r"제외|불허|불가|금지|제한|가능|만|대상|허용")
_NEG = {"불허", "불가", "금지", "제한"}
_ONLY = re.compile(r"(?:이외에는|외)(?:학생)?(?:수강신청|수강|신청)*(?:불허|불가|금지)")
_BROAD = re.compile(r"전학년|전체학년")


def _broadened(clause: str) -> bool:
    """본 수강신청 기간 안에 '전 학년·전체 학년' 으로 넓히는가. '수강신청 변경기간부터 … 전학년' 은 넓히지 않은 것으로 본다."""
    return any("변경기간" not in clause[max(0, m.start() - 15):m.start()] for m in _BROAD.finditer(clause))


def norm(text: str) -> str:
    """띄어쓰기와 가운뎃점을 지운다('물리·천문학부' = '물리천문학부')."""
    return _DOTS.sub("", text or "")


@dataclass(frozen=True)
class Student:
    college: str  # 개설대학 표기 (예: 공과대학)
    dept: str  # 개설학과 표기 (예: 화학생물공학부)
    year: int | None = None  # 모르면 None (학년 제한을 따지지 않는다)


class Units:
    """단과대·학과 이름 사전. depts = {학과: 단과대} (수강편람의 개설학과 → 개설대학)."""

    def __init__(self, depts: dict[str, str]):
        self.college_of = {norm(d): c for d, c in depts.items() if d}
        pats: list[tuple[str, str, str]] = []  # (찾을 말, 종류, 정식 이름)
        for college, aliases in COLLEGE_ALIASES.items():
            pats += [(norm(a), "college", college) for a in aliases]
        pats += [(d, "dept", d) for d in self.college_of]
        pats += [(a, "dept", norm(d)) for a, d in DEPT_ALIASES.items()]
        pats.sort(key=lambda p: -len(p[0]))  # 긴 이름부터 ('치의대' 가 '의대' 보다 먼저)
        self.pats = pats
        self.re = re.compile("|".join(re.escape(p[0]) for p in pats))
        self.lookup = {p[0]: (p[1], p[2]) for p in reversed(pats)}

    def find(self, seg: str) -> list[tuple[int, int, str, str]]:
        """조각 안의 이름들 [(시작, 끝, 종류, 정식 이름)]. 겹치면 긴 쪽."""
        return [(m.start(), m.end(), *self.lookup[m.group(0)]) for m in self.re.finditer(seg)]


def split_segments(clause: str) -> list[str]:
    """'/' 로 나눈다. 괄호 안과 숫자 사이(날짜 8/4)의 '/' 는 나누지 않는다."""
    out, buf, depth = [], [], 0
    for i, ch in enumerate(clause):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "/" and depth == 0 and not (0 < i < len(clause) - 1 and clause[i - 1].isdigit() and clause[i + 1].isdigit()):
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [s for s in out if s.strip()]


def _years(seg: str) -> tuple[set[int] | None, int | None]:
    """조각의 학년 제한: ({1, 2} 같은 목록, 'N학년 이상' 의 N). 없으면 (None, None)."""
    m = re.search(r"(\d)학년이상", seg)
    if m:
        return None, int(m.group(1))
    m = re.search(r"((?:\d,)*\d)학년(?:만|$|학생만)", seg) or re.search(r"본수강신청((?:\d,)*\d)학년", seg)
    if m:
        return {int(x) for x in m.group(1).split(",")}, None
    return None, None


def can_take(remark: str, section_dept: str, student: Student, units: Units) -> bool:
    """이 학생이 이 분반을 신청할 수 있으면 True. section_dept = 분반의 개설학과."""
    remark = remark or ""
    if _SPECIAL.search(remark):
        return False
    if "®" not in remark:
        return True
    clause = _NOTE.sub(" ", remark[remark.index("®") + 1:])
    broad = _broadened(norm(clause))
    for raw in split_segments(clause):
        verdict = _segment(norm(raw), section_dept, student, units, broad)
        if verdict is not None:
            return verdict
    return False


def _mentions(seg: str, units: Units) -> list[tuple[int, int, str, str]]:
    """조각의 이름 중 제한이 아닌 것은 뺀다.
    - 'X홈페이지'(안내), 'X … 201강좌'(다른 분반 이야기)
    - 자유전공학부에 다른 학과 조건이 붙은 것('자유전공학부(전기·정보공학부 주전공)', '(자유전공 포함)',
      '자유전공학부 학생 중 서양화과 진입생'): 학생이 어느 전공으로 갈지 모르므로 받기로 보지 않는다"""
    parens = [(g.start(), g.end()) for g in re.finditer(r"\([^()]*\)", seg)]
    out = []
    for a, e, k, n in units.find(seg):
        if seg.startswith("홈페이지", e):
            continue
        cue = _CUE.search(seg, e)
        if re.search(r"\d{3}강좌", seg[e:cue.start() if cue else len(seg)]):
            continue
        if n == "자유전공학부" and (any(x < a < y for x, y in parens) or seg.startswith(("(", "학생중"), e)):
            continue
        out.append((a, e, k, n))
    return out


def _cue_after(seg: str, e: int):
    """이름 뒤에 처음 오는 뜻말. 이름 바로 뒤 괄호('자연대(물리천문 제외)')는 괄호 안 이름들 몫이라 건너뛴다."""
    if seg.startswith("(", e):
        depth = 0
        for j in range(e, len(seg)):
            depth += seg[j] == "("
            depth -= seg[j] == ")"
            if depth == 0:
                e = j + 1
                break
    return _CUE.search(seg, e)


def _segment(seg: str, section_dept: str, st: Student, units: Units, broad: bool) -> bool | None:
    mentions = _mentions(seg, units)
    all_ok = "모든학생" in seg or "전체단과대" in seg
    tagwa = "타과생" in seg
    jujeon = "주전공" in seg and not mentions
    yrs, ymin = _years(seg)
    if not (mentions or all_ok or tagwa or jujeon or yrs or ymin):
        return None
    if "대상학부" in seg and not mentions:
        return False  # 대상 학부가 따로 정해져 있다(여기엔 이름이 없다)
    own = norm(st.dept) == norm(section_dept)
    sdept, scol = norm(st.dept), st.college

    # 이름마다 받기(in)·막기(bar)·빼기(out). 빼기 괄호에 학년이 있으면 그 학년만 뺀다
    role: dict[int, str] = {}
    out_years: dict[int, set[int]] = {}
    for g in re.finditer(r"\(([^()]*)\)", seg):  # (… 외), (… 제외)
        if re.search(r"(?:제외|외)$", g.group(1)):
            gy = {int(x) for x in re.findall(r"(\d)학년", g.group(1))}
            for i, (a, _, _, _) in enumerate(mentions):
                if g.start() < a < g.end():
                    role[i] = "out"
                    if gy:
                        out_years[i] = gy
    only = _ONLY.search(seg)
    for i, (a, e, _, _) in enumerate(mentions):
        if i in role:
            continue
        if only and e <= only.start():
            role[i] = "in"  # 'X 외 수강 불허' = X 만
            continue
        cue = _cue_after(seg, e)
        word = cue.group(0) if cue else ""
        role[i] = "out" if word == "제외" else "bar" if word in _NEG else "in"

    # 학과가 단과대 바로 뒤에 붙으면('공대_재료공학부', '자연대 수리과학부, 통계학과', '사범대학(수학교육과, …)')
    # 그 단과대는 그 학과만 받는다
    qualified: set[str] = set()
    last_college, last_end = None, -1
    for i, (a, e, k, n) in enumerate(mentions):
        gap = seg[last_end:a] if last_end >= 0 else "x"
        if k == "college":
            last_college, last_end = n, e
        elif last_college and re.fullmatch(r"[_:(,]*", gap) and role[i] == "in":
            qualified.add(last_college)
            last_end = e
        else:
            last_college, last_end = None, -1

    def hit(k: str, n: str) -> bool:
        return (k == "dept" and n == sdept) or (k == "college" and n == scol)

    def year_ok() -> bool:
        if st.year is None or broad:
            return True
        if ymin is not None:
            return st.year >= ymin
        return yrs is None or st.year in yrs

    for i, (_, _, k, n) in enumerate(mentions):
        if role[i] == "out" and hit(k, n) and not (i in out_years and st.year is not None and st.year not in out_years[i]):
            return False
    ins = [(k, n) for i, (_, _, k, n) in enumerate(mentions) if role[i] == "in"]
    bars = [(k, n) for i, (_, _, k, n) in enumerate(mentions) if role[i] == "bar"]
    bar_colleges = {n for k, n in bars if k == "college"}
    if any(hit(k, n) for k, n in bars if k == "dept"):
        return False
    if any(hit(k, n) for k, n in ins if k == "dept"):
        return year_ok()
    if scol in bar_colleges:
        return False
    # 막힌 단과대 안에서 따로 받는 학과('음대생 불허(국악과만 가능)')는 다른 학생에게 받기 목록이 아니다.
    # 막힌 이름이 설명 괄호에 다시 나와도('수리과학부 … 수강불허(수리과학부 진입예정자 …)') 받기 목록이 아니다
    general = [(k, n) for k, n in ins
               if (k, n) not in bars and not (k == "dept" and units.college_of.get(n) in bar_colleges)]
    if any(k == "college" and n == scol for k, n in general) and scol not in qualified:
        return year_ok()
    if tagwa:
        if re.search(r"타과생[^/]*?(?:금지|불허|불가|제한|정원외)", seg):
            return own and year_ok()
        if not general:
            return year_ok()
    if jujeon:
        return (not own) if re.search(r"주전공[^/]*?(?:불허|불가|금지)", seg) else own and year_ok()
    if general:
        return False
    if all_ok or bars or any(r == "out" for r in role.values()):
        return year_ok()
    return year_ok() if (yrs or ymin) else None
