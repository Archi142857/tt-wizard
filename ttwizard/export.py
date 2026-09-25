"""탐색 결과 → 웹 화면용 JSON.

화면은 이 JSON만 읽어서 그린다. 알고리즘과 화면을 잇는 유일한 접점이므로 필드를 바꾸면
web/ 쪽도 같이 바꿔야 한다. 점수·하한·퍼센트는 화면에 안 보여주기로 했으니 넣지 않는다
(디버그용으로 meta에만 남긴다).
"""

from __future__ import annotations

import json
from pathlib import Path

from .evaluate import Evaluation
from .models import DAY_KO, min_to_hm
from .search import SearchResult
from .travel import TravelMatrix


def evaluation_to_dict(rank: int, ev: Evaluation, travel: TravelMatrix) -> dict:
    def bname(b: str) -> str:
        bl = travel.buildings.get(b)
        return bl.name if bl and bl.name else b

    days = []
    for d, meetings in ev.days.items():
        legs = [
            {
                "from": lg.frm,
                "to": lg.to,
                "from_name": bname(lg.frm),
                "to_name": bname(lg.to),
                "minutes": round(lg.minutes, 1),
                "slack": None if lg.slack is None else round(lg.slack, 1),
            }
            for lg in ev.legs
            if lg.day == d
        ]
        days.append(
            {
                "day": d,
                "day_ko": DAY_KO[d],
                "classes": [
                    {
                        "start": min_to_hm(m.start),
                        "end": min_to_hm(m.end),
                        "building": m.building,
                        "building_name": bname(m.building) if m.building else "",
                        "room": m.room,
                        "course": next(
                            (s.course_name for s in ev.sections if m in s.meetings), ""
                        ),
                    }
                    for m in meetings
                ],
                "route": legs,
            }
        )
    return {
        "rank": rank,
        "sections": [
            {
                "course_id": s.course_id,
                "section_no": s.section_no,
                "course_name": s.course_name,
                "instructor": s.instructor,
            }
            for s in ev.sections
        ],
        "days": days,
        "campus_days": ev.campus_days,
        "travel_minutes": round(ev.travel_minutes, 1),
    }


def export_results(result: SearchResult, travel: TravelMatrix, home: str, path: str | Path) -> dict:
    payload = {
        "home": home,
        "home_name": travel.buildings[home].name if home in travel.buildings else home,
        "timetables": [evaluation_to_dict(i + 1, ev, travel) for i, ev in enumerate(result.ranked)],
        "buildings": {
            b.id: {"name": b.name, "lat": b.lat, "lon": b.lon} for b in travel.buildings.values()
        },
        "meta": {  # 화면에는 안 보여주는 값들
            "n_combinations": result.stats.n_combinations,
            "leaves": result.stats.leaves,
            "seconds": round(result.stats.seconds, 3),
            "lower_bound_minutes": result.lower_bound,
        },
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload
