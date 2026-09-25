"""수강신청 시스템(sugang.snu.ac.kr) 접근 — SNUTT(wafflestudio/snutt) batch 모듈이 쓰는 주소를 그대로 쓴다.

세 가지만 한다.
1. 현재 수강편람이 무슨 학기인지        (cc100ajax.action)
2. 그 학기 개설강좌 전체를 엑셀 한 파일로 (cc100InterfaceExcel.action, '엑셀 저장' 버튼과 같은 주소)
3. 첫 화면의 수강신청 일정표            (co010.action, 갱신 주기 판단용)

강좌별 상세 팝업(cc101ajax)은 호출하지 않는다 — 강좌 수만큼 요청이 나가서 서버에 부담을 준다.
SNUTT README의 경고대로 잦은 호출은 IP 차단을 받을 수 있으니 실행당 요청은 2~3회로 유지한다.

※ 이 파일은 실제 서버에 붙여 본 적이 없는 초안이다. 처음 돌릴 때 응답을 확인하고 고쳐 쓸 것.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import requests
from bs4 import BeautifulSoup

BASE = "https://sugang.snu.ac.kr"
MAIN_PAGE = "/sugang/co/co010.action"
COURSEBOOK_CONDITION = "/sugang/cc/cc100ajax.action?openUpDeptCd=&openDeptCd="
EXCEL_DOWNLOAD = "/sugang/cc/cc100InterfaceExcel.action"

# SNUTT SugangSnuRepository.DEFAULT_LECTURE_EXCEL_DOWNLOAD_PARAMS 와 같은 값
EXCEL_PARAMS = {
    "seeMore": "더보기",
    "srchBdNo": "", "srchCamp": "", "srchOpenSbjtFldCd": "", "srchCptnCorsFg": "",
    "srchCurrPage": "1",
    "srchExcept": "", "srchGenrlRemoteLtYn": "", "srchIsEngSbjt": "",
    "srchIsPendingCourse": "", "srchLsnProgType": "", "srchMrksApprMthdChgPosbYn": "", "srchMrksGvMthd": "",
    "srchOpenUpDeptCd": "", "srchOpenMjCd": "", "srchOpenPntMax": "", "srchOpenPntMin": "", "srchOpenSbjtDayNm": "",
    "srchOpenSbjtNm": "", "srchOpenSbjtTm": "", "srchOpenSbjtTmNm": "", "srchOpenShyr": "", "srchOpenSubmattCorsFg": "",
    **{f"srchOpenSubmattFgCd{i}": "" for i in range(1, 10)},
    "srchOpenDeptCd": "", "srchOpenUpSbjtFldCd": "",
    "srchPageSize": "9999",
    "srchProfNm": "", "srchSbjtCd": "", "srchSbjtNm": "", "srchTlsnAplyCapaCntMax": "", "srchTlsnAplyCapaCntMin": "",
    "srchTlsnRcntMax": "", "srchTlsnRcntMin": "",
    "workType": "EX",
}

# 학기 코드 (SNUTT SugangSnuCoursebookCondition)
SEMESTER_CODES = {
    "U000200001U000300001": "1",  # 1학기
    "U000200001U000300002": "S",  # 여름
    "U000200002U000300001": "2",  # 2학기
    "U000200002U000300002": "W",  # 겨울
}
CODE_OF_SEMESTER = {v: k for k, v in SEMESTER_CODES.items()}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tt-wizard/0.1 (student project; low volume)",
    "Referer": BASE + MAIN_PAGE,
}


@dataclass
class Coursebook:
    year: int
    code: str  # 20자 학기 코드

    @property
    def semester(self) -> str:
        return SEMESTER_CODES.get(self.code, self.code)

    @property
    def label(self) -> str:  # "2026-2"
        return f"{self.year}-{self.semester}"


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(BASE + MAIN_PAGE, timeout=30)  # 세션 쿠키
    return s


def current_coursebook(s: requests.Session) -> Coursebook:
    r = s.get(BASE + COURSEBOOK_CONDITION, timeout=30)
    r.raise_for_status()
    j = r.json()
    return Coursebook(year=int(j["currSchyy"]), code=str(j["currShtmFg"]) + str(j["currDetaShtmFg"]))


def download_excel(s: requests.Session, cb: Coursebook, lang: str = "ko") -> bytes:
    params = dict(EXCEL_PARAMS, srchLanguage=lang, srchOpenSchyy=str(cb.year), srchOpenShtm=cb.code)
    r = s.get(BASE + EXCEL_DOWNLOAD, params=params, timeout=120)
    r.raise_for_status()
    data = r.content
    # .xls(OLE2)는 D0 CF 11 E0, .xlsx(zip)는 50 4B 03 04 로 시작한다. HTML이 오면 로그인/차단 상황.
    if not (data.startswith(b"\xd0\xcf\x11\xe0") or data.startswith(b"PK\x03\x04")):
        raise RuntimeError(f"엑셀이 아닌 응답 ({len(data)} bytes): {data[:200]!r}")
    return data


def excel_extension(data: bytes) -> str:
    return ".xlsx" if data.startswith(b"PK\x03\x04") else ".xls"


_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def registration_windows(s: requests.Session) -> list[dict]:
    """첫 화면 일정표 → [{'type': '선착순수강신청', 'start': date, 'end': date}, ...]

    SNUTT RegistrationPeriodParseUtils 와 같은 셀렉터: .table-con table 의 tbody tr,
    th[data-th=구분] 의 텍스트와 td[data-th=일자] 의 "2026-01-30(금) ~ 2026-02-03(화)".
    """
    r = s.get(BASE + MAIN_PAGE, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.select_one(".table-con table")
    out: list[dict] = []
    if table is None:
        return out
    for row in table.select("tbody > tr"):
        th = row.select_one("th[data-th=구분]")
        td = row.select_one("td[data-th=일자]")
        if th is None or td is None:
            continue
        dates = _DATE_RE.findall(td.get_text(" ", strip=True))
        if not dates:
            continue
        start = date.fromisoformat(dates[0])
        end = date.fromisoformat(dates[1]) if len(dates) > 1 else start
        out.append({"type": th.get_text(" ", strip=True), "start": start, "end": end})
    return out
