"""건물 좌표와 건물 간 이동시간.

데이터 파일
- buildings.csv : building,name,lat,lon          (동 번호, 이름, 위경도)
- travel.csv    : from,to,minutes,source          (source: route / magicmap / tmap / naver / measured / estimate)

조회 순서
1. travel.csv 에 (from,to)가 있으면 그 값
2. 없고 (to,from)이 있으면 그 값 (대칭 가정, symmetric=True일 때)
3. 둘 다 없으면 좌표로 추정: 직선거리 × 우회계수 ÷ 보행속도
4. 좌표도 없으면 default_minutes

같은 건물이면 same_building_minutes (기본 0).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass(frozen=True)
class Building:
    id: str
    name: str
    lat: float | None
    lon: float | None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 위경도 사이 직선거리(m)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_buildings(path: str | Path) -> dict[str, Building]:
    out: dict[str, Building] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bid = row["building"].strip()
            lat = float(row["lat"]) if row.get("lat") else None
            lon = float(row["lon"]) if row.get("lon") else None
            out[bid] = Building(bid, row.get("name", "").strip(), lat, lon)
    return out


@dataclass
class TravelMatrix:
    buildings: dict[str, Building] = field(default_factory=dict)
    table: dict[tuple[str, str], float] = field(default_factory=dict)
    symmetric: bool = True
    walk_speed_kmh: float = 4.0  # 평지 보행 속도
    detour_factor: float = 1.35  # 직선거리 → 실제 경로 보정 (관악은 산이라 1.3~1.5)
    same_building_minutes: float = 0.0
    default_minutes: float = 15.0  # 좌표도 없을 때
    misses: set[tuple[str, str]] = field(default_factory=set)  # 추정으로 채운 쌍 (보고서용)

    @classmethod
    def load(cls, buildings_csv: str | Path, travel_csv: str | Path | None = None, **kw) -> "TravelMatrix":
        tm = cls(buildings=load_buildings(buildings_csv), **kw)
        if travel_csv and Path(travel_csv).exists():
            with open(travel_csv, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    tm.table[(row["from"].strip(), row["to"].strip())] = float(row["minutes"])
        return tm

    def estimate(self, a: str, b: str) -> float | None:
        ba, bb = self.buildings.get(a), self.buildings.get(b)
        if not ba or not bb or ba.lat is None or bb.lat is None:
            return None
        meters = haversine_m(ba.lat, ba.lon, bb.lat, bb.lon) * self.detour_factor
        return meters / (self.walk_speed_kmh * 1000 / 60)

    def minutes(self, a: str, b: str) -> float:
        if a == b:
            return self.same_building_minutes
        if (a, b) in self.table:
            return self.table[(a, b)]
        if self.symmetric and (b, a) in self.table:
            return self.table[(b, a)]
        self.misses.add((a, b))
        est = self.estimate(a, b)
        return self.default_minutes if est is None else est

    def closure(self, ids) -> "TravelMatrix":
        """ids 사이를 다른 지점을 거쳐 가는 경우까지 본 최단 시간(Floyd–Warshall)을 표로 가진 새 행렬.

        출입구가 여러 곳인 건물은 한쪽 출입구로 들어가 다른 쪽으로 나가는 지름길 구실을 해서, 건물별
        최단 경로로 만든 행렬(마법 지도 표, 경사 반영 표)은 삼각부등식을 자주 어긴다. 그러면 '수업을 더 넣어도
        비용이 줄지 않는다'가 깨져 부분 비용이 하한이 아니게 된다. 이 행렬로 잰 부분 비용은 늘 하한이다.
        """
        ids = list(dict.fromkeys(ids))
        misses = set(self.misses)
        d = {(a, b): 0.0 if a == b else self.minutes(a, b) for a in ids for b in ids}
        self.misses = misses  # 하한 계산용 조회는 '추정으로 채운 쌍' 기록에 넣지 않는다
        for k in ids:
            for a in ids:
                dak = d[(a, k)]
                for b in ids:
                    v = dak + d[(k, b)]
                    if v < d[(a, b)]:
                        d[(a, b)] = v
        return replace(self, table={k: v for k, v in d.items() if k[0] != k[1]}, misses=set())

    def check_triangle(self, ids: list[str] | None = None, tolerance: float = 0.5) -> list[tuple[str, str, str, float]]:
        """삼각부등식 위반 쌍을 찾는다: t(a,c) > t(a,b) + t(b,c) + tolerance.

        출입구가 여러 곳인 건물을 거치는 지름길, 지도 API 값과 좌표 추정값의 혼합 등으로 깨진다.
        search.py 는 closure() 행렬로 하한을 재므로 위반이 있어도 결과가 틀리지 않는다. 보고서의 '행렬 검증' 항목.
        """
        ids = ids or list(self.buildings)
        bad = []
        for a in ids:
            for b in ids:
                if a == b:
                    continue
                ab = self.minutes(a, b)
                for c in ids:
                    if c in (a, b):
                        continue
                    via = ab + self.minutes(b, c)
                    direct = self.minutes(a, c)
                    if direct > via + tolerance:
                        bad.append((a, b, c, round(direct - via, 1)))
        return bad

    def save(self, travel_csv: str | Path) -> None:
        with open(travel_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["from", "to", "minutes", "source"])
            for (a, b), m in sorted(self.table.items()):
                w.writerow([a, b, f"{m:.1f}", ""])
