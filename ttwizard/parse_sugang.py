"""수강편람 엑셀 → Section 목록.

수강신청 시스템(sugang.snu.ac.kr) 강좌검색의 '엑셀 저장' 파일을 읽는다.
열 이름(2023.01 기준, SNUTT 파서 주석에서): 교과구분, 개설대학, 개설학과, 이수과정, 학년,
교과목번호, 강좌번호, 교과목명, 부제명, 학점, 강의, 실습, 수업교시, 수업형태,
강의실(동-호)(#연건, *평창), 주담당교수, 정원, 수강신청인원, 비고, 강의언어, 개설상태

열 이름이 조금 바뀌어도 버티도록 '포함 문자열'로 열을 찾는다.
- .xls  → xlrd 필요   (pip install xlrd)
- .xlsx → openpyxl 필요
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from .models import DAY_INDEX, Meeting, Section, hm_to_min

# 월(09:30~10:45) 형태. 공백이 섞여도 잡히게 \s* 허용.
_TIME_RE = re.compile(r"([월화수목금토일])\s*\(\s*(\d{1,2}):(\d{2})\s*~\s*(\d{1,2}):(\d{2})\s*\)")

# 강의실 칸에 이런 값이 오면 '위치 없음'으로 본다.
_NO_LOCATION_WORDS = ("미정", "온라인", "비대면", "원격", "e-learning", "etl", "ETL", "none", "None", "nan")

# 필요한 열과, 그 열을 찾을 때 쓰는 포함 문자열 후보들
_COLUMN_HINTS = {
    "course_id": ("교과목번호",),
    "section_no": ("강좌번호",),
    "course_name": ("교과목명",),
    "subtitle": ("부제명",),
    "time": ("수업교시",),
    "room": ("강의실",),
    "instructor": ("주담당교수", "담당교수", "교수"),
    "department": ("개설학과",),
    "college": ("개설대학",),
    "credit": ("학점",),
    "classification": ("교과구분",),
    "program": ("이수과정",),
    "status": ("개설상태",),
}


def _find_header_row(df: pd.DataFrame) -> int:
    """'교과목번호'가 들어 있는 행을 헤더로 본다(파일 맨 위에 제목 줄이 몇 개 있다)."""
    for i in range(min(len(df), 15)):
        row = ["" if pd.isna(c) else str(c) for c in df.iloc[i].tolist()]
        if any("교과목번호" in cell for cell in row):
            return i
    raise ValueError("헤더 행을 찾지 못했습니다. '교과목번호' 열이 있는 수강편람 엑셀인지 확인하세요.")


def _map_columns(header: list[str]) -> dict[str, int]:
    """열 이름 → 인덱스. 후보 문자열이 포함된 첫 열을 쓴다."""
    idx: dict[str, int] = {}
    for key, hints in _COLUMN_HINTS.items():
        for hint in hints:
            hit = next((i for i, h in enumerate(header) if hint in h), None)
            if hit is not None:
                idx[key] = hit
                break
    missing = [k for k in ("course_id", "section_no", "course_name", "time", "room") if k not in idx]
    if missing:
        raise ValueError(f"필수 열을 찾지 못했습니다: {missing}. 헤더: {header}")
    return idx


def parse_building(place: str) -> tuple[str, str]:
    """강의실 원문 → (동 번호, 캠퍼스).

    SNUTT의 PlaceInfo 규칙을 따른다.
      '301-118'      → ('301', '관악')
      '220-1-201'    → ('220-1', '관악')   (세 조각이고 가운데가 한 글자면 앞 둘을 합침)
      '083-302'      → ('83', '관악')      (앞자리 0 제거)
      '#101-1-2'     → ('101-1', '연건')
      '*201'         → ('201', '평창')
      '미정' / ''     → ('', '관악')
    """
    text = (place or "").strip()
    campus = "관악"
    if text.startswith("#"):
        campus = "연건"
        text = text[1:]
    elif text.startswith("*"):
        campus = "평창"
        text = text[1:]
    text = text.replace("(무선랜제공)", "").strip()
    if not text or any(w in text for w in _NO_LOCATION_WORDS):
        return "", campus

    parts = [p for p in text.split("-") if p and not re.fullmatch(r"[A-Za-z]+", p)]
    if not parts:
        return "", campus
    if len(parts) == 3 and len(parts[1]) == 1:
        building = f"{parts[0]}-{parts[1]}"
    else:
        building = parts[0]
    building = building.lstrip("0") or "0"
    return building, campus


def parse_meetings(time_text: str, room_text: str) -> tuple[list[Meeting], set[str]]:
    """'월(09:30~10:45)/수(09:30~10:45)', '301-118/301-118' → Meeting 목록과 캠퍼스 집합.

    강의실 조각 수가 시간 조각 수와 같으면 짝지어 쓰고, 하나면 전부에 적용, 없으면 빈 위치.
    """
    time_text = "" if time_text is None else str(time_text)
    room_text = "" if room_text is None else str(room_text)
    if time_text.strip().lower() in ("", "nan", "none"):
        return [], set()

    matches = _TIME_RE.findall(time_text)
    rooms = [r.strip() for r in room_text.split("/")] if room_text.strip().lower() not in ("", "nan", "none") else []
    if len(rooms) == len(matches):
        pass
    elif len(rooms) == 1:
        rooms = rooms * len(matches)
    else:
        # 개수가 안 맞으면 첫 강의실만 믿고 나머지는 같은 곳으로 가정 (보고서에 예외 건수로 기록)
        rooms = (rooms[:1] or [""]) * len(matches)

    meetings: list[Meeting] = []
    campuses: set[str] = set()
    for (day, sh, sm, eh, em), room in zip(matches, rooms):
        building, campus = parse_building(room)
        campuses.add(campus)
        meetings.append(
            Meeting(
                day=DAY_INDEX[day],
                start=hm_to_min(f"{sh}:{sm}"),
                end=hm_to_min(f"{eh}:{em}"),
                building=building,
                room=room,
            )
        )
    return meetings, campuses


def _norm_section_no(value) -> str:
    """엑셀에서 1.0 / '1' / '001' 로 들어오는 강좌번호를 '001'로 통일."""
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(3) if s.isdigit() else s


def parse_sugang_excel(path: str | Path, campus: str | None = "관악") -> list[Section]:
    """수강편람 엑셀 파일 하나를 Section 목록으로. campus=None이면 연건·평창도 포함."""
    path = Path(path)
    engine = "xlrd" if path.suffix.lower() == ".xls" else None
    raw = pd.read_excel(path, header=None, engine=engine, dtype=str)
    h = _find_header_row(raw)
    header = ["" if pd.isna(c) else str(c).strip() for c in raw.iloc[h].tolist()]
    col = _map_columns(header)
    body = raw.iloc[h + 1 :]

    def cell(row, key, default=""):
        i = col.get(key)
        if i is None:
            return default
        v = row.iloc[i]
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return default
        v = str(v).strip()
        return default if v.lower() in ("nan", "none", "<na>") else v

    sections: list[Section] = []
    for _, row in body.iterrows():
        course_id = cell(row, "course_id")
        if not course_id:
            continue
        meetings, campuses = parse_meetings(cell(row, "time"), cell(row, "room"))
        if campus is not None and campuses and campuses != {campus}:
            continue  # 연건·평창 강좌 제외
        name = cell(row, "course_name")
        subtitle = cell(row, "subtitle")
        if subtitle:
            name = f"{name} ({subtitle})"
        try:
            credit = float(cell(row, "credit", "0") or 0)
        except ValueError:
            credit = 0.0
        sections.append(
            Section(
                course_id=course_id,
                section_no=_norm_section_no(cell(row, "section_no")),
                course_name=name,
                meetings=tuple(meetings),
                instructor=cell(row, "instructor"),
                department=cell(row, "department") or cell(row, "college"),
                credit=credit,
                classification=cell(row, "classification"),
                program=cell(row, "program"),
                status=cell(row, "status"),
            )
        )
    return sections


# ---------- JSON 저장/불러오기 (파싱은 학기당 몇 번, 탐색은 JSON에서) ----------

def sections_to_json(sections: Iterable[Section], path: str | Path) -> None:
    data = [
        {
            "course_id": s.course_id,
            "section_no": s.section_no,
            "course_name": s.course_name,
            "instructor": s.instructor,
            "department": s.department,
            "credit": s.credit,
            "classification": s.classification,
            "program": s.program,
            "status": s.status,
            "meetings": [
                {"day": m.day, "start": m.start, "end": m.end, "building": m.building, "room": m.room}
                for m in s.meetings
            ],
        }
        for s in sections
    ]
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def sections_from_json(path: str | Path) -> list[Section]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        Section(
            course_id=d["course_id"],
            section_no=d["section_no"],
            course_name=d["course_name"],
            meetings=tuple(Meeting(**m) for m in d["meetings"]),
            instructor=d.get("instructor", ""),
            department=d.get("department", ""),
            credit=d.get("credit", 0.0),
            classification=d.get("classification", ""),
            program=d.get("program", ""),
            status=d.get("status", ""),
        )
        for d in data
    ]


def location_stats(sections: Iterable[Section], program: str | None = "학사") -> dict:
    """보고서용 수치. 기본은 학사·설강·수업시간 있는 강좌만 센다.

    - located_ratio            : 그중 강의실이 전부 확정된 비율 (편람 게시 후 시간에 따라 오르는 값)
    - multi_building_ratio     : 분반이 둘 이상인 과목 중 분반이 서로 다른 동에서 열리는 과목 비율
    - buildings                : 강의가 실제로 열리는 동 수
    수업시간이 없는 강좌(논문연구 등)는 위치가 있을 수 없으므로 분모에서 뺀다.
    """
    all_secs = list(sections)
    timed = [s for s in all_secs if s.meetings and (s.status in ("", "설강")) and (program is None or s.program in ("", program))]
    located = [s for s in timed if s.has_location]
    by_course: dict[str, list[Section]] = {}
    for s in timed:
        by_course.setdefault(s.course_id, []).append(s)
    multi = {cid: ss for cid, ss in by_course.items() if len(ss) >= 2}
    multi_diff = [cid for cid, ss in multi.items() if len(set().union(*(s.buildings for s in ss))) >= 2]
    buildings = set().union(*(s.buildings for s in timed)) if timed else set()
    return {
        "sections_total": len(all_secs),
        "sections_timed": len(timed),
        "sections_located": len(located),
        "located_ratio": round(len(located) / len(timed), 3) if timed else 0.0,
        "courses": len(by_course),
        "courses_multi_section": len(multi),
        "courses_multi_building": len(multi_diff),
        "multi_building_ratio": round(len(multi_diff) / len(multi), 3) if multi else 0.0,
        "buildings": len(buildings),
        "program": program or "전체",
    }
