"""분반 조합 하나를 요일별 경로로 펴서 비용을 계산한다.

하루 경로 = 집 → 수업1 → 수업2 → … → 집.
비용 = 주간 총 이동시간 + late_weight × 지각 분(연강 사이 여유가 이동시간보다 짧은 만큼)
      + campus_day_weight × 등교 일수 + gap_weight × 공강 분

기본은 이동시간 단일 기준(late_weight만 켬). 나머지 가중치는 0으로 두고 확장 항목으로 남긴다.

강의실 미정 수업은 어디서 열리는지 모르므로 이동도 지각도 만들지 않는다. 시간만 차지하고, 그 앞의 쉬는
시간은 다음 위치 확정 수업으로 가는 길에 보탠다(가는 길 어딘가에서 열린다고 보는 셈). 그날 첫 위치 확정
수업은 앞에 미정 수업이 있어도 집에서 오는 길이라 시간 제약이 없다.

부분 조합(과목 일부만 고른 상태)에 대해서도 계산할 수 있고, 삼각부등식이 성립하는 이동시간
행렬에서는 수업을 더 끼워 넣어도 이동시간·지각이 줄지 않으므로 그 값이 완성 조합의 하한이 된다.
실제 행렬은 출입구가 여러 곳인 건물을 거치는 지름길 때문에 삼각부등식을 어기므로, 탐색(search.py)은
하한을 잴 때 TravelMatrix.closure() 로 만든 행렬을 넘긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import DAY_KO, Meeting, Section
from .travel import TravelMatrix


@dataclass
class Leg:
    """경로의 한 구간 (이전 위치 → 다음 위치)."""

    day: int
    frm: str
    to: str
    depart: int | None  # 이전 수업 끝 (집에서 출발이면 None)
    arrive_by: int | None  # 다음 수업 시작 (집으로 귀가면 None)
    minutes: float
    slack: float | None  # 여유 = 다음 시작 − 이전 끝 − 이동시간. 음수면 지각


@dataclass
class Weights:
    travel: float = 1.0
    late: float = 2.0  # 지각 1분당 페널티. 아주 크게 주면 사실상 하드 제약
    campus_day: float = 0.0
    gap: float = 0.0
    long_gap_threshold: int = 180  # 이 이상 비면 '집에 갔다 오는' 선택지도 고려 (확장용, 현재 미사용)


@dataclass
class Evaluation:
    sections: list[Section]
    travel_minutes: float = 0.0
    late_minutes: float = 0.0
    gap_minutes: float = 0.0
    campus_days: int = 0
    legs: list[Leg] = field(default_factory=list)
    days: dict[int, list[Meeting]] = field(default_factory=dict)  # day → 시간순 미팅
    cost: float = 0.0

    def summary(self) -> str:
        days = "".join(DAY_KO[d] for d in sorted(self.days))
        return (
            f"이동 {self.travel_minutes:.0f}분/주 · 등교 {self.campus_days}일({days}) · "
            f"지각 {self.late_minutes:.0f}분 · 비용 {self.cost:.1f}"
        )


def evaluate(
    sections: list[Section],
    travel: TravelMatrix,
    home: str,
    weights: Weights | None = None,
) -> Evaluation:
    w = weights or Weights()
    ev = Evaluation(sections=list(sections))

    # 요일별로 미팅을 모아 시간순 정렬 → 경로 확정
    by_day: dict[int, list[Meeting]] = {}
    for s in sections:
        for m in s.meetings:
            by_day.setdefault(m.day, []).append(m)
    for d in by_day:
        by_day[d].sort(key=lambda m: (m.start, m.end))
    ev.days = dict(sorted(by_day.items()))
    ev.campus_days = len(by_day)

    for d, meetings in ev.days.items():
        prev_loc, prev_end = home, None
        placed = False  # 그날 위치 확정 수업을 이미 지났는지
        spare = 0.0  # 마지막 위치 확정 수업 뒤, 강의실 미정 수업들 앞의 쉬는 시간 합
        for m in meetings:
            if not m.building:  # 강의실 미정 (모듈 설명 참조)
                if placed:
                    spare += m.start - prev_end
                ev.legs.append(Leg(d, prev_loc, prev_loc, prev_end, m.start, 0.0, None))
                prev_end = m.end
                continue
            t = travel.minutes(prev_loc, m.building)
            slack = (spare + m.start - prev_end - t) if placed else None
            ev.legs.append(Leg(d, prev_loc, m.building, prev_end, m.start, t, slack))
            ev.travel_minutes += t
            if slack is not None:
                if slack < 0:
                    ev.late_minutes += -slack
                else:
                    ev.gap_minutes += slack
            prev_loc, prev_end, placed, spare = m.building, m.end, True, 0.0
        # 귀가
        t = travel.minutes(prev_loc, home)
        ev.legs.append(Leg(d, prev_loc, home, prev_end, None, t, None))
        ev.travel_minutes += t

    ev.cost = (
        w.travel * ev.travel_minutes
        + w.late * ev.late_minutes
        + w.campus_day * ev.campus_days
        + w.gap * ev.gap_minutes
    )
    return ev
