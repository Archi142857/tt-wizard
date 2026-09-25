"""자료형 정의.

시간은 모두 '하루 시작부터의 분'(0~1440)으로 다룬다. 09:30 → 570.
요일은 0=월 … 4=금 (토·일은 5·6, 탐색에서는 거의 안 쓰임).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

DAY_KO = "월화수목금토일"
DAY_INDEX = {ch: i for i, ch in enumerate(DAY_KO)}


def hm_to_min(text: str) -> int:
    """'09:30' → 570"""
    h, m = text.strip().split(":")
    return int(h) * 60 + int(m)


def min_to_hm(minute: int) -> str:
    """570 → '09:30'"""
    return f"{minute // 60:02d}:{minute % 60:02d}"


@dataclass(frozen=True)
class Meeting:
    """한 번의 수업 시간. 월수 분반은 Meeting 2개를 가진다."""

    day: int  # 0=월 … 4=금
    start: int  # 분
    end: int  # 분
    building: str  # 동 번호 문자열, 예: "301", "220-1". 미정이면 ""
    room: str = ""  # 원문 강의실 표기, 예: "301-118"

    @property
    def day_ko(self) -> str:
        return DAY_KO[self.day]

    def overlaps(self, other: "Meeting") -> bool:
        """같은 요일에 시간이 겹치면 True. 끝나는 시각 == 시작 시각은 겹침 아님."""
        return self.day == other.day and self.start < other.end and other.start < self.end

    def __str__(self) -> str:  # 디버깅용
        where = self.building or "미정"
        return f"{self.day_ko}({min_to_hm(self.start)}~{min_to_hm(self.end)}) {where}"


@dataclass(frozen=True)
class Section:
    """분반(강좌) 하나. (course_id, section_no)가 전역 키."""

    course_id: str  # 교과목번호, 예: "M1234.000100"
    section_no: str  # 강좌번호, 예: "001"
    course_name: str
    meetings: tuple[Meeting, ...]
    instructor: str = ""
    department: str = ""
    credit: float = 0.0
    classification: str = ""  # 교과구분(전필/전선/교양 …)

    @property
    def key(self) -> str:
        return f"{self.course_id}-{self.section_no}"

    @property
    def buildings(self) -> set[str]:
        return {m.building for m in self.meetings if m.building}

    @property
    def has_location(self) -> bool:
        return all(m.building for m in self.meetings) and len(self.meetings) > 0

    def conflicts_with(self, other: "Section") -> bool:
        return any(a.overlaps(b) for a in self.meetings for b in other.meetings)


@dataclass
class Course:
    """과목 하나와 그 후보 분반들. 사용자가 뺀 분반은 sections에서 제거해 둔다."""

    course_id: str
    name: str
    sections: list[Section] = field(default_factory=list)

    @property
    def n_sections(self) -> int:
        return len(self.sections)


def group_into_courses(sections: Iterable[Section]) -> dict[str, Course]:
    """Section 목록을 교과목번호 기준으로 Course로 묶는다."""
    courses: dict[str, Course] = {}
    for s in sections:
        c = courses.get(s.course_id)
        if c is None:
            c = courses[s.course_id] = Course(course_id=s.course_id, name=s.course_name)
        c.sections.append(s)
    return courses
