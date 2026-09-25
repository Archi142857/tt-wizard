"""TSP 하한.

과목을 클러스터로 보고, 클러스터 쌍 거리 = 두 과목의 어떤 분반·어떤 건물 조합이든 가장 가까운
이동시간으로 잡은 뒤, 집을 포함한 TSP(모든 과목을 한 번씩 방문하는 최단 순회)를 푼다.

주간 시간표의 총 이동은 요일별 닫힌 경로(집→…→집)들의 합인데, 이를 집에서 이어 붙이면 모든
과목을 방문하는 닫힌 경로 하나가 되고, 삼각부등식 아래에서 TSP 순회는 그런 경로 중 최단이다.
따라서 어떤 시간표도 이 값보다 짧을 수 없다. 탐색의 가지치기와 보고서의 '이상적 동선 대비 손해'
지표에 쓴다(화면에는 표시하지 않음).

과목 12개까지는 Held–Karp DP로 정확히 푼다(2^12 × 12^2 ≈ 60만 연산).
"""

from __future__ import annotations

from functools import lru_cache

from .models import Course
from .travel import TravelMatrix


def cluster_distance(a: Course, b: Course, travel: TravelMatrix) -> float:
    best = float("inf")
    for s in a.sections:
        for t in b.sections:
            ba, bb = s.buildings, t.buildings
            if not ba or not bb:
                return 0.0  # 위치 미정이 있으면 하한은 0으로 (보수적)
            for x in ba:
                for y in bb:
                    best = min(best, travel.minutes(x, y))
    return 0.0 if best == float("inf") else best


def home_distance(c: Course, home: str, travel: TravelMatrix) -> float:
    best = float("inf")
    for s in c.sections:
        if not s.buildings:
            return 0.0
        for x in s.buildings:
            best = min(best, travel.minutes(home, x))
    return 0.0 if best == float("inf") else best


def tsp_lower_bound(courses: list[Course], travel: TravelMatrix, home: str) -> float:
    """집 + 과목들을 한 번씩 방문하는 최단 순회 길이(분). 과목이 없으면 0."""
    n = len(courses)
    if n == 0:
        return 0.0
    # 노드 0 = 집, 1..n = 과목
    dist = [[0.0] * (n + 1) for _ in range(n + 1)]
    for i, c in enumerate(courses, start=1):
        dist[0][i] = dist[i][0] = home_distance(c, home, travel)
        for j in range(i + 1, n + 1):
            dist[i][j] = dist[j][i] = cluster_distance(c, courses[j - 1], travel)

    if n > 12:
        return _mst_bound(dist)

    full = (1 << n) - 1

    @lru_cache(maxsize=None)
    def dp(mask: int, last: int) -> float:
        # mask: 방문한 과목 집합(비트 i-1 = 과목 i), last: 마지막 과목(1..n)
        if mask == (1 << (last - 1)):
            return dist[0][last]
        prev_mask = mask & ~(1 << (last - 1))
        best = float("inf")
        for k in range(1, n + 1):
            if prev_mask & (1 << (k - 1)):
                best = min(best, dp(prev_mask, k) + dist[k][last])
        return best

    return min(dp(full, last) + dist[last][0] for last in range(1, n + 1))


def _mst_bound(dist: list[list[float]]) -> float:
    """과목이 많을 때 쓰는 느슨한 하한: 최소 신장 트리 가중치 (TSP ≥ MST)."""
    n = len(dist)
    in_tree = [False] * n
    best = [float("inf")] * n
    best[0] = 0.0
    total = 0.0
    for _ in range(n):
        u = min((i for i in range(n) if not in_tree[i]), key=lambda i: best[i])
        in_tree[u] = True
        total += best[u]
        for v in range(n):
            if not in_tree[v] and dist[u][v] < best[v]:
                best[v] = dist[u][v]
    return total
