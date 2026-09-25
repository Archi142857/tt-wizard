"""분반 쌍 충돌(시간 겹침) 행렬.

하드 제약은 '시간 겹침' 하나만. 이동 가능 여부는 evaluate 쪽 페널티로 다룬다.
서로 다른 과목의 모든 분반 쌍에 대해 미리 계산해 두고 탐색 중엔 조회만 한다.
"""

from __future__ import annotations

from .models import Course, Section


class ConflictMatrix:
    def __init__(self, courses: list[Course]):
        # 전역 인덱스 부여
        self.sections: list[Section] = []
        self.course_of: list[int] = []  # section index → course index
        for ci, c in enumerate(courses):
            for s in c.sections:
                self.sections.append(s)
                self.course_of.append(ci)
        n = len(self.sections)
        self.index: dict[str, int] = {s.key: i for i, s in enumerate(self.sections)}
        # conflicts[i] = i와 시간이 겹치는 분반 인덱스 집합 (다른 과목만)
        self.conflicts: list[set[int]] = [set() for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                if self.course_of[i] == self.course_of[j]:
                    continue
                if self.sections[i].conflicts_with(self.sections[j]):
                    self.conflicts[i].add(j)
                    self.conflicts[j].add(i)

    def ok_with(self, i: int, chosen: list[int]) -> bool:
        """분반 i가 지금까지 고른 분반들과 충돌하지 않으면 True."""
        ci = self.conflicts[i]
        return not any(j in ci for j in chosen)

    @property
    def n_pairs_conflicting(self) -> int:
        return sum(len(s) for s in self.conflicts) // 2
