"""분반 선택 탐색: 백트래킹 + 분기 한정.

변수 = 과목, 도메인 = 분반, 제약 = 시간 겹침 없음, 목적 = evaluate.cost 최소.

- 과목은 분반 수가 적은 순으로 고른다(MRV).
- 분반을 고를 때마다 충돌 행렬로 겹침을 걸러낸다(forward checking).
- 지금까지 고른 분반만으로 계산한 비용이 현재 K번째 해보다 크면 그 가지를 버린다.
  (수업을 더 넣어도 비용이 줄지 않으므로 부분 비용이 하한 — evaluate.py 설명 참조)
- 완성 조합은 상위 K개만 힙으로 유지한다.

과목 5~7개 × 분반 2~4개면 조합이 수천~수만 개라 가지치기 없이도 1초 안에 끝난다.
조합이 수십만을 넘으면 SearchStats.leaves가 커지는 걸 보고 SA 같은 휴리스틱으로 넘어간다.
"""

from __future__ import annotations

import heapq
import itertools
import time
from dataclasses import dataclass, field

from .conflicts import ConflictMatrix
from .evaluate import Evaluation, Weights, evaluate
from .models import Course, Section
from .travel import TravelMatrix


@dataclass
class SearchStats:
    n_courses: int = 0
    n_combinations: int = 0  # 분반 수의 곱 (이론상 전체)
    nodes: int = 0  # 방문한 부분 조합 수
    leaves: int = 0  # 평가한 완성 조합 수
    pruned_conflict: int = 0
    pruned_bound: int = 0
    seconds: float = 0.0


@dataclass
class SearchResult:
    ranked: list[Evaluation]  # 비용 오름차순
    stats: SearchStats
    lower_bound: float | None = None  # TSP 하한 (bound.py에서 채움, 선택)

    def top(self, k: int = 1) -> list[Evaluation]:
        return self.ranked[:k]


def search(
    courses: list[Course],
    travel: TravelMatrix,
    home: str,
    top_k: int = 10,
    weights: Weights | None = None,
    use_bound: bool = True,
) -> SearchResult:
    t0 = time.perf_counter()
    weights = weights or Weights()
    courses = [c for c in courses if c.sections]
    order = sorted(range(len(courses)), key=lambda i: courses[i].n_sections)  # MRV
    cm = ConflictMatrix(courses)

    stats = SearchStats(n_courses=len(courses))
    stats.n_combinations = 1
    for c in courses:
        stats.n_combinations *= c.n_sections

    # 힙에는 (-cost, tiebreak, Evaluation) — 최대힙처럼 써서 K번째(가장 나쁜) 해를 꼭대기에 둔다
    heap: list[tuple[float, int, Evaluation]] = []
    counter = itertools.count()

    def worst_kept() -> float:
        return -heap[0][0] if len(heap) >= top_k else float("inf")

    chosen_idx: list[int] = []  # ConflictMatrix 전역 인덱스
    chosen_sec: list[Section] = []

    def backtrack(depth: int) -> None:
        stats.nodes += 1
        if depth == len(order):
            ev = evaluate(chosen_sec, travel, home, weights)
            stats.leaves += 1
            if ev.cost < worst_kept():
                item = (-ev.cost, next(counter), ev)
                if len(heap) < top_k:
                    heapq.heappush(heap, item)
                else:
                    heapq.heapreplace(heap, item)
            return

        course = courses[order[depth]]
        for s in course.sections:
            gi = cm.index[s.key]
            if not cm.ok_with(gi, chosen_idx):
                stats.pruned_conflict += 1
                continue
            chosen_idx.append(gi)
            chosen_sec.append(s)
            if use_bound and len(heap) >= top_k:
                partial = evaluate(chosen_sec, travel, home, weights)
                if partial.cost >= worst_kept():
                    stats.pruned_bound += 1
                    chosen_idx.pop()
                    chosen_sec.pop()
                    continue
            backtrack(depth + 1)
            chosen_idx.pop()
            chosen_sec.pop()

    backtrack(0)
    ranked = sorted((ev for _, _, ev in heap), key=lambda e: e.cost)
    stats.seconds = time.perf_counter() - t0
    return SearchResult(ranked=ranked, stats=stats)


def brute_force(courses: list[Course], travel: TravelMatrix, home: str, weights: Weights | None = None) -> list[Evaluation]:
    """검증용 완전탐색. search()와 결과가 같아야 한다 (tests/ 참조)."""
    weights = weights or Weights()
    out: list[Evaluation] = []
    for combo in itertools.product(*(c.sections for c in courses if c.sections)):
        if any(a.conflicts_with(b) for a, b in itertools.combinations(combo, 2)):
            continue
        out.append(evaluate(list(combo), travel, home, weights))
    out.sort(key=lambda e: e.cost)
    return out
